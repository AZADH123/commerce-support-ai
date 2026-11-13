import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import api
from src.backend import db
from src.backend.models import Case, CaseEvent, Payment, RefundAction, User
from src.backend.seed import DEMO_SUBS
from src.integrations.stripe_sig import WebhookVerificationError, verify_stripe_signature
from src.services import cases as cases_service
from src.services.webhooks import process_event

SECRET = "whsec_test_secret"
PAYMENT_INTENT = "pi_test_123"
AMOUNT = 7999
CURRENCY = "usd"


def _user_id(session, key: str) -> int:
    return session.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one().id


def _sign(raw: bytes, secret: str = SECRET, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    signed = f"{ts}.".encode() + raw
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


def _event(
    event_id: str,
    kind: str,
    *,
    refund_id: str = "re_test_1",
    payment_intent: str = PAYMENT_INTENT,
    amount: int = AMOUNT,
    currency: str = CURRENCY,
    status: str | None = None,
) -> dict:
    if status is None:
        status = "succeeded" if kind == "succeeded" else "failed"
    return {
        "id": event_id,
        "type": f"refund.{kind}",
        "data": {
            "object": {
                "id": refund_id,
                "object": "refund",
                "payment_intent": payment_intent,
                "amount": amount,
                "currency": currency,
                "status": status,
            }
        },
    }


def _prepare_stripe_case(session, *, currency: str = CURRENCY) -> Case:
    payment = session.execute(select(Payment).where(Payment.order_id == 1001)).scalar_one()
    payment.provider = "stripe"
    payment.provider_payment_id = PAYMENT_INTENT
    payment.currency = currency
    session.commit()

    alice = _user_id(session, "alice")
    case = cases_service.request_refund(session, customer_id=alice, order_id=1001, reason="broken")
    return cases_service.approve(session, case_id=case.id, reviewer_id=_user_id(session, "reviewer"), reason="ok")


def test_valid_signature_accepted():
    raw = json.dumps(_event("evt_sig_ok", "succeeded")).encode()
    payload = verify_stripe_signature(raw, _sign(raw), SECRET)
    assert payload["id"] == "evt_sig_ok"


def test_tampered_body_rejected():
    raw = json.dumps(_event("evt_tamper", "succeeded")).encode()
    signature = _sign(raw)
    tampered = raw.replace(b"succeeded", b"failed")
    with pytest.raises(WebhookVerificationError):
        verify_stripe_signature(tampered, signature, SECRET)


def test_stale_signature_rejected():
    raw = json.dumps(_event("evt_stale", "succeeded")).encode()
    stale = _sign(raw, timestamp=int(time.time()) - 3600)
    with pytest.raises(WebhookVerificationError):
        verify_stripe_signature(raw, stale, SECRET)


def test_invalid_signature_rejected_at_endpoint(seeded, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    raw = json.dumps(_event("evt_bad_sig", "succeeded")).encode()
    with TestClient(api.app) as client:
        response = client.post(
            "/api/webhooks/stripe",
            content=raw,
            headers={"Stripe-Signature": "t=1,v1=deadbeef"},
        )
    assert response.status_code == 400


def test_webhook_endpoint_deduplicates_delivery(seeded, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    session = db.get_session()
    case = _prepare_stripe_case(session)
    case_id = case.id
    session.close()

    raw = json.dumps(_event("evt_endpoint_dup", "succeeded")).encode()
    signature = _sign(raw)
    with TestClient(api.app) as client:
        first = client.post("/api/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature})
        second = client.post("/api/webhooks/stripe", content=raw, headers={"Stripe-Signature": signature})
    assert first.status_code == 200
    assert first.json()["status"] == "PROCESSED"
    assert second.status_code == 200
    assert second.json()["status"] == "PROCESSED"  # acknowledged duplicate

    check = db.get_session()
    try:
        events = check.execute(select(CaseEvent).where(CaseEvent.case_id == case_id)).scalars().all()
        assert [e.transition for e in events].count("REFUNDED") == 1
        assert check.get(Case, case_id).status == "REFUNDED"
    finally:
        check.close()


def test_process_event_is_idempotent(seeded):
    session = db.get_session()
    try:
        case = _prepare_stripe_case(session)
        event = _event("evt_dup", "succeeded")
        first = process_event(session, provider="stripe", event=event)
        second = process_event(session, provider="stripe", event=event)
        assert first.id == second.id
        events = session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id)).scalars().all()
        assert [e.transition for e in events].count("REFUNDED") == 1
    finally:
        session.close()


def test_amount_mismatch_surfaces_needs_attention(seeded):
    session = db.get_session()
    try:
        case = _prepare_stripe_case(session)
        event = _event("evt_mismatch", "succeeded", amount=1)
        record = process_event(session, provider="stripe", event=event)
        assert record.status == "PROCESSED"
        assert "amount mismatch" in (record.error or "")
        assert session.get(Case, case.id).status == "NEEDS_ATTENTION"
        events = session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id)).scalars().all()
        assert "NEEDS_ATTENTION" in [e.transition for e in events]
    finally:
        session.close()


def test_late_failure_does_not_regress_refunded(seeded):
    session = db.get_session()
    try:
        case = _prepare_stripe_case(session)
        process_event(session, provider="stripe", event=_event("evt_ok", "succeeded"))
        late = process_event(session, provider="stripe", event=_event("evt_late_fail", "failed"))
        assert late.status == "IGNORED"
        assert session.get(Case, case.id).status == "REFUNDED"
        action = session.execute(
            select(RefundAction).where(RefundAction.case_id == case.id)
        ).scalar_one()
        assert action.status == "SUCCEEDED"
    finally:
        session.close()


def test_late_success_recovers_needs_attention(seeded):
    session = db.get_session()
    try:
        case = _prepare_stripe_case(session)
        process_event(session, provider="stripe", event=_event("evt_fail", "failed"))
        assert session.get(Case, case.id).status == "NEEDS_ATTENTION"

        recovered = process_event(session, provider="stripe", event=_event("evt_late_ok", "succeeded"))
        assert recovered.status == "PROCESSED"
        assert session.get(Case, case.id).status == "REFUNDED"
    finally:
        session.close()


def test_unmatched_event_is_stored(seeded):
    session = db.get_session()
    try:
        _prepare_stripe_case(session)
        record = process_event(
            session,
            provider="stripe",
            event=_event("evt_unknown", "succeeded", payment_intent="pi_other", refund_id="re_other"),
        )
        assert record.status == "UNMATCHED"
    finally:
        session.close()


def test_pending_then_succeeded_is_not_a_regression(seeded):
    session = db.get_session()
    try:
        case = _prepare_stripe_case(session)
        pending = process_event(
            session, provider="stripe", event=_event("evt_pending", "updated", status="pending")
        )
        assert pending.status == "IGNORED"
        assert session.get(Case, case.id).status == "APPROVED"

        done = process_event(session, provider="stripe", event=_event("evt_done", "succeeded"))
        assert done.status == "PROCESSED"
        assert session.get(Case, case.id).status == "REFUNDED"
    finally:
        session.close()
