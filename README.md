# AI Customer Support Agent (Multi-Agent)

![CI](https://github.com/Pragatheswar-72/support-agent/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A multi-agent customer-support system for an e-commerce store. An orchestrator
routes each request to a specialist agent (orders, refunds, payments, FAQ) that
calls real backend tools to resolve it — with guardrails, error handling, and
automatic human-escalation on failure.

## Live demo

**▶️ Live app:** https://support-agent-htg6lfc8qdjeez9bhx8b9o.streamlit.app/
(free-tier hosting — if it shows "app went to sleep," click "Yes, get this app
back up," it wakes in under a minute)

## Screenshots

| Order lookup | Guardrail refusal |
|:---:|:---:|
| ![Order lookup](demo/01_order_lookup.png) | ![Guardrail refusal](demo/02_guardrail_refusal.png) |

| Guardrail enforced at the tool level | FAQ answer + session stats |
|:---:|:---:|
| ![Trace showing eligibility check](demo/02b_guardrail_trace_expanded.png) | ![FAQ and sidebar](demo/03_faq_and_sidebar.png) |

The right-hand pair shows the actual mechanism: `check_refund_eligibility`
returns `"eligible": false` for a shipped (not delivered) order, so
`initiate_refund` never even attempts the refund — the rule is enforced in
the tool's code, not just requested in a prompt.

| FastAPI interactive docs (`/docs`) | Real `/chat` request + response |
|:---:|:---:|
| ![API docs](demo/04_api_docs_endpoint.png) | ![API response](demo/04b_api_docs_response.png) |

Same orchestrator, different front door: this is the identical order-lookup
request from the screenshot above, but made directly against the REST API
instead of the chat UI — same reply, same tool trace, same backend.

## What it does

- Understands natural-language support requests
- Routes to the right specialist agent (LangGraph orchestration)
- Calls tools that read **and modify** a backend (order status, refunds, payments)
- Remembers context across turns (e.g. "refund it" resolves to the last order discussed)
- Enforces guardrails at the tool level (e.g. refunds only on delivered orders)
- Handles errors with a retry, then escalates to a human with a ticket ID
- Shows a live agent trace: which agent handled the request and which tools it called
- Tracks token usage per session and caches repeated FAQ answers to save quota
- Exposes the same orchestrator over a **FastAPI** REST endpoint, not just the chat UI
- Ships with a **routing evaluation harness** that measures LLM classification accuracy on a curated dataset, separate from unit tests

## Tech

LangGraph multi-agent orchestration · DeepSeek V4.1 Flash tool-calling (official API)
· SQLite backend (SQLAlchemy) · Streamlit · FastAPI · pytest

## Architecture

```
              Streamlit UI (app.py)   FastAPI (api.py)
                        |                   |
                        +--------+----------+
                                 v
                   +--------------------+
                   |   ORCHESTRATOR     |  <- classifies intent, routes,
                   |   (LangGraph)      |     holds conversation memory
                   +---------+----------+
        +----------+---------+----------+-----------+
        v          v         v          v            v
   +--------+ +--------+ +--------+ +--------+  (no match / fails)
   | ORDER  | | REFUND | |PAYMENT | |  FAQ   |        |
   | agent  | | agent  | | agent  | | agent  |        v
   +---+----+ +---+----+ +---+----+ +---+----+   +----------+
       | tools    | tools    | tools    |        | ESCALATE |
       v          v          v          v        | to human |
   +---------------------------------------+     +----------+
   |   SQLite backend                      |
   |   orders / payments / refunds tables  |
   +---------------------------------------+
```

## How it works

1. The orchestrator (a LangGraph graph) classifies the message into ORDER,
   REFUND, PAYMENT, FAQ, or ESCALATE.
2. The matching specialist agent decides which tool(s) to call and with what
   arguments (DeepSeek tool-calling), then turns the tool result into a
   natural-language reply.
3. Tools read from and write to a SQLite database — refunds and payments are
   real state changes, not simulated text.
4. Guardrails are enforced in the tools themselves (not just the prompt): for
   example `initiate_refund` always re-checks eligibility before acting, so
   an LLM can't talk its way around the rule.
5. If the whole pipeline fails (e.g. an API outage or rate limit), it retries
   once, then calls `escalate_to_human`, which returns a ticket ID instead of
   crashing.
6. Conversation memory tracks the last order discussed, so follow-up messages
   like "refund it" resolve correctly across agent switches.

## Run locally

1. `python -m venv venv` and activate it
   (`.\venv\Scripts\Activate.ps1` on Windows, `source venv/bin/activate` on macOS/Linux).
2. `pip install -r requirements.txt`
3. For a new setup, copy `.env.example` to `.env` and replace the
   `DEEPSEEK_API_KEY` placeholder with your official DeepSeek API key.
   If `.env` already exists, edit only the needed settings; do not overwrite it.
4. `python -m src.backend.seed` — creates and seeds the SQLite database.
5. `streamlit run app.py`

## Run the API (FastAPI)

```
uvicorn api:app --reload
```

Then open interactive docs at http://localhost:8000/docs. Example flow:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "where is order 1001?"}'

# reuse the returned session_id to keep conversation memory across turns
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "refund it, it arrived broken", "session_id": "<id from above>"}'
```

Every request is logged as structured JSON (method, path, status, latency).
The Streamlit UI and the API both call the same `src/orchestrator.py`, so the
agent logic is written once and consumed by either a human (UI) or a machine
(API).

## Tests

```
pytest
```

Tests cover: every tool against a seeded in-memory database (including
the refund-eligibility guardrail), orchestrator routing for all five paths
(mocked LLM, no API key needed), conversation memory, retry/escalation
behavior on a forced failure, the FastAPI endpoints (session handling,
validation, mocked orchestrator), DeepSeek request configuration and a complete tool-call round trip with mocked HTTP,
and a regression test for a real bug found
during manual testing (a model looping on a tool call without ever
answering — see the commit history for the fix).

## Evaluation

A routing evaluation harness measures whether the router LLM classifies
realistic (and deliberately tricky) customer messages correctly — this is
different from the unit tests, which only check the graph wiring with a
mocked LLM:

```
python eval/run_eval.py --dry-run   # validates the dataset, no API calls
python eval/run_eval.py             # calls the real LLM, reports accuracy
```

The bundled 21-scenario dataset (`eval/eval_dataset.json`) can be used to
measure routing accuracy for your configured DeepSeek model. Live evaluation
requires `DEEPSEEK_API_KEY`; unit tests and `--dry-run` require no API key.

## Docker

```
docker build -t support-agent .
docker run -p 8501:8501 -e DEEPSEEK_API_KEY support-agent
```

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. On https://share.streamlit.io, create an app from the repo, main file `app.py`.
3. In the app's **Secrets**, add:
   ```
   DEEPSEEK_API_KEY = "your_key_here"
   DEEPSEEK_MODEL = "deepseek-flash"   # optional
   ```
   Never commit the real key — `.env` is git-ignored.
4. That's it — the SQLite file isn't committed to the repo, but `src/tools.py`
   auto-seeds the database on first import if it's empty, so a fresh
   deployment works with no extra startup step.

## Cost

DeepSeek API usage is billed to your DeepSeek account. FAQ-answer caching
reduces repeat specialist calls. Check your provider account for current pricing.

## Configuration

- `DEEPSEEK_API_KEY` - required, loaded from the environment or local `.env`.
- `DEEPSEEK_MODEL` - optional, defaults to `deepseek-flash` (DeepSeek V4.1 Flash).

The router and every specialist share `get_llm()`, using `ChatOpenAI` from
`langchain-openai` with the explicit DeepSeek key and
`https://api.deepseek.com` Chat Completions endpoint. Thinking is disabled
on every request with `extra_body={"thinking": {"type": "disabled"}}`, including
requests with tools. See the [official DeepSeek tool-call example](https://api-docs.deepseek.com/guides/tool_calls/).
Each provider call has a 60-second timeout and no SDK retries; the existing
orchestrator retries the pipeline once, then escalates on failure. Provider
exception bodies are omitted from retry logs and escalation context.

## Windows PowerShell

Run from the repository directory. Stop an existing FastAPI process with
Ctrl+C in its terminal, then install dependencies and restart:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn api:app --reload
```

For a new environment, first run `python -m venv .venv`. Configure
`DEEPSEEK_API_KEY` in your local `.env` before making live requests. In another
PowerShell terminal, run this read-only order lookup:

```powershell
$body = @{ message = "Where is order 1001?" } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/chat" -ContentType "application/json" -Body $body
$result | ConvertTo-Json -Depth 10
if ($result.agent -ne "order") { throw "Expected order agent" }
if (-not ($result.trace | Where-Object { $_.tool -in @("get_order_status", "get_order_details", "track_shipment") -and $_.args.order_id -eq 1001 })) { throw "Expected order 1001 lookup in trace" }
```
