import json

from src.api.routes import chat as chat_route

FAKE_RESULT = {
    "reply": "Your order 1001 has been delivered.",
    "agent": "order",
    "trace": [
        {
            "agent": "order",
            "tool": "get_order_status",
            "args": {"order_id": 1001},
            "result": {"order_id": 1001, "status": "delivered"},
        }
    ],
    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    "cached": False,
}


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_config_no_auth(client):
    r = client.get("/api/auth/config")
    assert r.status_code == 200
    assert r.json()["client_id"] == "commerce-support-web"


def test_me_requires_auth(client):
    assert client.get("/api/me").status_code == 401


def test_me_returns_identity(client):
    client.set_principal("alice")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["role"] == "customer"
    assert r.json()["email"] == "alice@example.com"


def test_chat_requires_auth(client):
    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_chat_returns_redacted_trace(client, monkeypatch):
    monkeypatch.setattr(chat_route, "run_orchestrator", lambda *a, **k: FAKE_RESULT)
    client.set_principal("alice")
    r = client.post("/chat", json={"message": "where is order 1001?"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Your order 1001 has been delivered."
    assert body["trace"] == [{"agent": "order", "tool": "get_order_status"}]
    # Internal tool args/results must never reach the customer.
    assert '"args"' not in json.dumps(body)
    assert '"result"' not in json.dumps(body)
    assert "conversation_id" in body


def test_chat_restores_conversation_history(client, monkeypatch):
    captured = []

    def fake(user_message, history=None):
        captured.append(list(history or []))
        return FAKE_RESULT

    monkeypatch.setattr(chat_route, "run_orchestrator", fake)
    client.set_principal("alice")
    r1 = client.post("/chat", json={"message": "where is order 1001?"})
    cid = r1.json()["conversation_id"]
    r2 = client.post("/chat", json={"message": "refund it", "conversation_id": cid})
    assert r2.json()["conversation_id"] == cid
    assert len(captured[0]) == 0
    assert len(captured[1]) == 2


def test_chat_rejects_empty_message(client):
    client.set_principal("alice")
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_chat_unexpected_error_does_not_expose_credentials(client, monkeypatch):
    def fail(*_a, **_k):
        raise RuntimeError("Authorization: Bearer test-secret-credential")

    monkeypatch.setattr(chat_route, "run_orchestrator", fail)
    client.set_principal("alice")
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 502
    assert "test-secret-credential" not in r.text


def test_cross_user_conversation_access_denied(client, monkeypatch):
    monkeypatch.setattr(chat_route, "run_orchestrator", lambda *a, **k: FAKE_RESULT)
    client.set_principal("alice")
    cid = client.post("/chat", json={"message": "hi"}).json()["conversation_id"]
    client.set_principal("bob")
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_orders_scoped_to_owner(client):
    client.set_principal("alice")
    assert [o["order_id"] for o in client.get("/api/orders").json()] == [1001, 1002, 1003]
    client.set_principal("bob")
    assert [o["order_id"] for o in client.get("/api/orders").json()] == [1004, 1005, 1006]


def test_review_endpoints_require_reviewer(client):
    client.set_principal("alice")
    assert client.get("/api/review/cases").status_code == 403
    assert client.get("/api/review/cases/1").status_code == 403
    assert client.post("/api/review/cases/1/approve", json={}).status_code == 403


def test_reviewer_queue_and_decision_flow(client, case_factory):
    case = case_factory("alice", 1001, "Arrived broken")
    client.set_principal("reviewer")

    queue = client.get("/api/review/cases").json()
    assert queue["total"] == 1
    assert queue["items"][0]["id"] == case.id
    assert queue["items"][0]["status"] == "PENDING_REVIEW"

    approved = client.post(f"/api/review/cases/{case.id}/approve", json={"reason": "Approved"}).json()
    assert approved["status"] == "APPROVED"
    assert approved["decision_reason"] == "Approved"
    assert [e["transition"] for e in approved["events"]] == ["CREATED", "APPROVED"]

    # Customer sees the decision on their own case detail.
    client.set_principal("alice")
    detail = client.get(f"/api/cases/{case.id}").json()
    assert detail["status"] == "APPROVED"


def test_reviewer_reject_requires_reason(client, case_factory):
    case = case_factory("alice", 1001, "Arrived broken")
    client.set_principal("reviewer")
    r = client.post(f"/api/review/cases/{case.id}/reject", json={})
    assert r.status_code == 422
