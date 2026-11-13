import json

from src.api.routes import chat as chat_route

CITATION = {
    "document_id": 1,
    "title": "Shipping policy",
    "version": 1,
    "topic": "shipping",
    "effective_date": "2026-01-01",
    "source": "Store Operations Handbook 2026, §2 Shipping (v1)",
    "chunk_index": 0,
    "snippet": "Standard shipping takes 3-5 business days.",
    "score": 0.91,
}

FAKE_RESULT = {
    "reply": "Standard shipping takes 3-5 business days.",
    "agent": "faq",
    "trace": [
        {
            "agent": "faq",
            "tool": "answer_faq",
            "args": {"question": "how long does shipping take"},
            "result": {
                "answer": "Standard shipping takes 3-5 business days.",
                "citations": [CITATION],
            },
        }
    ],
    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    "cached": False,
}


def test_chat_returns_and_persists_citations(client, monkeypatch):
    monkeypatch.setattr(chat_route, "run_orchestrator", lambda *a, **k: FAKE_RESULT)
    client.set_principal("alice")

    response = client.post("/chat", json={"message": "How long does shipping take?"})
    assert response.status_code == 200
    body = response.json()
    assert body["citations"][0]["version"] == 1
    assert body["citations"][0]["source"].startswith("Store Operations Handbook")

    conversation = client.get(f"/api/conversations/{body['conversation_id']}").json()
    assistant = [m for m in conversation["messages"] if m["role"] == "assistant"][0]
    assert assistant["citations"][0]["snippet"].startswith("Standard shipping")


def test_reviewer_case_detail_exposes_execution(client, case_factory):
    case = case_factory("alice", 1001, "Arrived broken")
    client.set_principal("reviewer")

    approved = client.post(f"/api/review/cases/{case.id}/approve", json={"reason": "Approved"})
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "APPROVED"
    assert body["action"]["status"] == "PENDING"
    assert body["action"]["amount_cents"] == 7999
    assert body["action"]["currency"] == "usd"
    assert any(e["event_type"] == "refund.approved" for e in body["outbox"])

    detail = client.get(f"/api/review/cases/{case.id}").json()
    assert detail["action"]["idempotency_key"] == f"refund-case-{case.id}"


def test_customer_case_detail_hides_internal_execution(client, case_factory):
    case = case_factory("alice", 1001, "Arrived broken")
    client.set_principal("reviewer")
    client.post(f"/api/review/cases/{case.id}/approve", json={"reason": "Approved"})

    client.set_principal("alice")
    detail = client.get(f"/api/cases/{case.id}").json()
    assert detail["status"] == "APPROVED"
    assert detail["execution_status"] == "PENDING"
    assert "action" not in detail
    assert "idempotency_key" not in json.dumps(detail)
    assert "last_error" not in json.dumps(detail)
