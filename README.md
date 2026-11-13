# AI Customer Support Agent — Phase 2 (Payments · Reliability · Policy KB)

A multi-agent customer-support system. A LangGraph orchestrator routes each
message to a specialist (orders, refunds, payments, FAQ) that calls real
backend tools. Phase 1 added PostgreSQL, Keycloak OIDC, owner-scoped data, and a
durable refund review workflow. **Phase 2** executes reviewer-approved refunds
through a payment sandbox, makes execution reliable (transactional outbox,
Taskiq/Redis workers, idempotency, reconciliation), reconciles provider
webhooks, notifies customers through Mailpit, and answers FAQ questions from a
versioned pgvector policy knowledge base with structured citations.

## Architecture

```
                React SPA (frontend/, Vite + TS + Router + TanStack Query)
                        |  Authorization: Bearer <access_token> (memory only)
                        v
   +-------------------- FastAPI (api.py) --------------------------------+
   |  /chat   /api/orders /api/conversations /api/cases /api/review/*     |
   |  /api/auth/config /api/me   /api/webhooks/stripe (signature-verified)|
   |  OIDC validation | owner scoping | reviewer authorization            |
   +----+---------------------+---------------------------+---------------+
        |                     |                           |
        v                     v                           v
  agent orchestration   business services           persistence
  src/orchestrator.py   src/services/*              src/backend/models.py
  src/agents/*          - cases / refund_execution   SQLAlchemy + Alembic
  src/tools.py          - webhooks / notifications          |
                        - conversations                      v
        |                     |                    PostgreSQL (pgvector image)
        |                     +--> outbox_events ----> Dispatcher
        |                     |                              |
        v                     v                              v
   DeepSeek chat         policy knowledge base         Redis -> Taskiq workers
   (unchanged)           policy_documents/chunks      - refund execution
                         (portable vector column)      - notification delivery
                                                              |
                        Stripe test mode  <---- payment adapter |--> Mailpit SMTP
                        (or local adapter)                     (UI :8025)
```

## Refund case state diagram

```
                              reviewer approve (one transaction)
  PENDING_REVIEW ───────────────────────────────────────────────► APPROVED
        │                                                             │
        │ reviewer reject                                             │ dispatcher -> worker
        v                                                             v
     REJECTED                                                     PROCESSING
                                                                      │
                    provider success / webhook reconcile              │
              ┌───────────────────────────────────────────────────────┤
              v                                                       │
          REFUNDED  ◄──────── late provider success ──────────────── NEEDS_ATTENTION
        (terminal)                                                   ^
                                                                     │
                              permanent failure / ambiguous outcome /│
                              missing payment reference / mismatch  ─┘
```

## What changed in Phase 2

- **Commerce/payment adapters** — `src/integrations/commerce.py`
  (deterministic order/ownership lookup) and `src/integrations/payments.py`
  (`LocalPaymentAdapter` + concrete `StripePaymentAdapter` test mode). Provider
  submission lives only in the authorized execution service.
- **Durable execution** — `src/services/refund_execution.py`: approval writes
  the case transition, the single `RefundAction`, and the outbox record in one
  transaction; a dispatcher (`src/outbox/dispatcher.py`,
  `python -m src.tasks.dispatch`) and Taskiq/Redis worker execute it.
- **Webhook reconciliation** — `POST /api/webhooks/stripe` verifies the raw-body
  signature, deduplicates event ids, validates action/payment/amount/currency,
  and never regresses a finalized case.
- **Notifications** — durable `Notification` rows + outbox, delivered by a
  worker over SMTP to Mailpit.
- **Policy knowledge base** — versioned policies with pgvector embeddings,
  ingestion CLI, active-version selection, structured citations in `/chat`, and
  the policy version recorded on each refund case.
- **React** — policy citations in chat, a customer case timeline
  (APPROVED → PROCESSING → REFUNDED / NEEDS_ATTENTION) with bounded polling, and
  reviewer execution/recovery visibility. OpenAPI types regenerated.

## Prerequisites

- Python 3.11+ (tested 3.12), Node 20+, npm, Docker.

## Quick start (PowerShell)

```powershell
# 1. Infrastructure: PostgreSQL+pgvector, Redis, Mailpit, Keycloak
docker compose up -d

# 2. Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configure environment (do not overwrite an existing .env)
Copy-Item .env.example .env   # set DEEPSEEK_API_KEY; keep PAYMENT_PROVIDER=local for the deterministic demo

# 4. Schema, demo data, policies
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m src.backend.seed
.\.venv\Scripts\python.exe -m src.knowledge.ingest

# 5. API (terminal 1)
.\.venv\Scripts\python.exe -m uvicorn api:app --reload

# 6. Outbox dispatcher (terminal 2)
.\.venv\Scripts\python.exe -m src.tasks.dispatch --loop

# 7. Taskiq worker (terminal 3)
.\.venv\Scripts\taskiq.exe worker src.tasks.broker:broker src.tasks.refund_tasks

# 8. Frontend (terminal 4)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 (Mailpit UI: http://localhost:8025).

> **pgvector note:** Phase 2 requires the `pgvector/pgvector:pg16` image (the
> bundled compose file). A Postgres volume created by a plain `postgres` image
> does not have the `vector` extension; either install it in that database or
> recreate the **dev** volume with `docker compose down -v` (this deletes local
> demo data only).

## Demo users

Keycloak realm `support`, client `commerce-support-web`; password `password`.

| User                   | Role     | Orders owned |
|------------------------|----------|--------------|
| `alice@example.com`    | customer | 1001 (delivered), 1002 (shipped), 1003 (placed) |
| `bob@example.com`      | customer | 1004 (delivered), 1005 (cancelled), 1006 (delivered) |
| `reviewer@example.com` | reviewer | — |

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEPSEEK_API_KEY` | — | DeepSeek chat key (required for live chat) |
| `DEEPSEEK_MODEL` | `deepseek-flash` | Chat model id |
| `DATABASE_URL` | compose Postgres | SQLAlchemy URL (falls back to `SUPPORT_AGENT_DB_URL`, then SQLite) |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_CLIENT_ID` | local Keycloak realm | OIDC validation |
| `OIDC_REVIEWER_ROLE` | `reviewer` | Realm role for staff |
| `PAYMENT_PROVIDER` | `local` | `local` (deterministic) or `stripe` (test mode) |
| `STRIPE_SECRET_KEY` | — | Stripe **test** secret (`sk_test_...`) |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signing secret (`whsec_...`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Taskiq broker |
| `EMAIL_TRANSPORT` | `memory` | `smtp` for Mailpit, `memory` for tests |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_SENDER` | `localhost` / `1025` / no-reply | Mailpit SMTP |
| `EMBEDDING_PROVIDER` | `hashing` | `hashing` (offline) or `openai` |
| `EMBEDDING_DIM` | `384` | Must match the embedding model / vector column |

Frontend public config: `VITE_OIDC_REDIRECT_URI` (optional; defaults to
`{origin}/callback`). No secrets belong in `VITE_*`.

## Payment provider: Stripe test mode

**Selected provider:** Stripe test mode, called directly over the Stripe HTTP
API (no SDK dependency). The adapter sends an `Idempotency-Key` of
`refund-case-<case_id>` and never trusts model-generated amounts or references.

Account setup (sandbox only):

1. Create a Stripe account and stay in **test mode**.
2. Copy the test secret key (`sk_test_...`) into `STRIPE_SECRET_KEY`.
3. Provision a synthetic test payment for the demo order:
   ```powershell
   $env:STRIPE_SECRET_KEY = "sk_test_..."
   .\.venv\Scripts\python.exe scripts\stripe_provision.py --order 1001
   ```
   This creates a confirmed test PaymentIntent and points order 1001's payment
   row at it (`provider=stripe`).
4. Forward webhooks and copy the printed signing secret into
   `STRIPE_WEBHOOK_SECRET` (`whsec_...`):
   ```powershell
   stripe listen --forward-to http://localhost:8000/api/webhooks/stripe
   ```
5. Set `PAYMENT_PROVIDER=stripe` and restart the API and worker.

For a fully deterministic local demo, keep `PAYMENT_PROVIDER=local`; the local
adapter succeeds in-process and needs no network or credentials.

## Reliability model

- **Approval transaction** — `PENDING_REVIEW → APPROVED`, the `APPROVED` audit
  event, the single `RefundAction` (unique `case_id`), and the `refund.approved`
  outbox row commit together.
- **Stable idempotency key** — derived from the case id and reused on every
  retry, so the provider never creates a second refund.
- **Duplicate jobs** — a worker claims `PENDING/RETRYABLE → SUBMITTING` with a
  compare-and-swap; an already-`SUCCEEDED`/terminal action is a no-op.
- **Retryable vs permanent vs uncertain** — retryable re-enqueues with backoff;
  permanent moves the case to `NEEDS_ATTENTION`; uncertain outcomes are
  reconciled against the provider before resubmitting, and unresolved ones
  become `NEEDS_ATTENTION`.
- **Worker crash after provider acceptance** — the action stays `SUBMITTING`;
  the dispatcher's stale recovery re-enqueues it, and execution reconciles the
  provider result instead of resubmitting.
- **Dispatcher recovery of unsent outbox rows** — nothing is deleted on
  dispatch; `PENDING` rows are re-dispatched on every pass, with backoff and a
  `FAILED` ceiling after repeated enqueue failures.

## Webhooks

`POST /api/webhooks/stripe` verifies the `Stripe-Signature` HMAC over the exact
raw request body (with a timestamp tolerance), deduplicates `(provider,
event_id)`, and validates the provider, payment reference, amount, and currency
against the stored `RefundAction` before applying any transition. Late,
duplicate, and out-of-order events are acknowledged without regressing a
finalized case; a late success can still recover a `NEEDS_ATTENTION` case.

## Notifications

Every case update creates a durable `Notification` row plus an outbox event; the
notification worker sends it over SMTP. Locally, Mailpit captures mail at
http://localhost:8025. Delivery is **at-least-once**: a status CAS prevents
duplicate sends on retry, and SMTP has no provider idempotency, so a crash after
the provider accepts but before the local `SENT` commit can resend.

## Policy knowledge base

- Tables: `policy_documents` (store, topic, title, version, effective date,
  source, content, active) and `policy_chunks` (chunk index, text, vector).
- **Embeddings are configured separately from DeepSeek chat.** Default
  `hashing` embedder: deterministic, offline, **384 dimensions**. To use a real
  model, set `EMBEDDING_PROVIDER=openai`, `EMBEDDING_BASE_URL`,
  `EMBEDDING_API_KEY`, `EMBEDDING_MODEL=text-embedding-3-small`, and
  `EMBEDDING_DIM=1536`.
- Ingestion is repeatable:
  ```powershell
  .\.venv\Scripts\python.exe -m src.knowledge.ingest
  .\.venv\Scripts\python.exe -m src.knowledge.ingest --reindex   # force re-embedding
  ```
  Changing the embedding model/dimension requires a migration (or recreating the
  vector column), then `--reindex`.
- Only the highest **effective** version per `(store, topic)` is active.
  Retrieval returns structured citations (document id, title, version, source,
  effective date, chunk index, snippet, score). Retrieved text is treated as
  untrusted content; refund eligibility remains a business rule, and the active
  refund policy version is recorded on each case.

## API

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET  | `/health` | — | Liveness |
| GET  | `/api/auth/config` | — | Public OIDC config (PKCE) |
| GET  | `/api/me` | any | Identity |
| POST | `/chat` | any | Chat (owner-scoped; returns `citations`) |
| GET  | `/api/orders` | any | Own orders |
| GET  | `/api/conversations` / `/{id}` | any | Own conversations |
| GET  | `/api/cases` / `/{id}` | any | Own cases + timeline + `execution_status` |
| GET  | `/api/review/cases` | reviewer | Queue (pagination + filters) |
| GET  | `/api/review/cases/{id}` | reviewer | Case + `action`, `notifications`, `outbox` |
| POST | `/api/review/cases/{id}/approve` | reviewer | Approve (creates action + outbox) |
| POST | `/api/review/cases/{id}/reject` | reviewer | Reject (reason required) |
| POST | `/api/webhooks/stripe` | signature | Provider webhook reconciliation |

## Tests & verification

Backend (deterministic, from repo root):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Frontend (from `frontend/`):

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

Deterministic coverage includes: duplicate jobs, concurrent approval, invalid
webhook signatures, delayed/out-of-order events, uncertain refund outcomes,
worker crash after provider acceptance, outbox retry/recovery, active policy
selection, citations, and notification retries.

**Live sandbox checks** (require the Docker stack and, for Stripe, a test key):

```powershell
docker compose up -d
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m src.backend.seed
.\.venv\Scripts\python.exe -m src.knowledge.ingest
.\.venv\Scripts\python.exe -m uvicorn api:app --reload
.\.venv\Scripts\python.exe -m src.tasks.dispatch --loop
cd frontend; npm run dev
npx playwright install chromium
npm run test:e2e
```

## Copyable demo (PowerShell)

```powershell
# Chat: policy citation
$body = @{ message = "How long does shipping take?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/chat" -ContentType "application/json" -Body $body |
  Select-Object reply, citations
```

Then, in the React app: sign in as alice, ask for a refund on order 1001, sign
out; sign in as reviewer, approve the case; sign back in as alice and watch the
timeline reach **Refunded**. Mailpit (http://localhost:8025) shows the
notification. With `PAYMENT_PROVIDER=local` the refund is deterministic; with
Stripe test mode it exercises the sandbox and its webhooks.

## Security notes

- Tokens stay in memory (never URLs/persistent storage); identity and role come
  from validated OIDC claims, never from model arguments or request bodies.
- Customer responses redact tool internals and provider error bodies; reviewer
  execution details are behind reviewer authorization.
- Webhook signatures are verified over the raw body; event ids are deduplicated.
- Keep `DEEPSEEK_API_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET` out of
  Git; `.env` is git-ignored. No secrets are logged.

## License

MIT.
