import threading
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select

from src.backend import db
from src.backend.models import Case, CaseEvent, Notification, OutboxEvent, RefundAction, User, utcnow
from src.backend.seed import DEMO_SUBS, seed
from src.integrations.payments import (
    PermanentProviderError,
    RefundResult,
    RetryableProviderError,
    UncertainProviderError,
)
from src.outbox.dispatcher import dispatch_pending
from src.services import cases as cases_service
from src.services import refund_execution


def _user_id(session, key: str) -> int:
    return session.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one().id


class FakeAdapter:
    """Deterministic adapter with scripted behaviors and reconciliation results."""

    def __init__(self):
        self.calls: list[dict] = []
        self.behaviors: list[object] = []
        self.get_results: list[object] = []
        self.refunds: dict[str, RefundResult] = {}

    def create_refund(self, *, payment_ref, amount_cents, currency, idempotency_key):
        self.calls.append(
            {
                "payment_ref": payment_ref,
                "amount_cents": amount_cents,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        if self.behaviors:
            behavior = self.behaviors.pop(0)
            if isinstance(behavior, Exception):
                raise behavior
        result = RefundResult(
            status="succeeded",
            provider_refund_id=f"re_{idempotency_key}",
            amount_cents=amount_cents,
            currency=currency,
        )
        self.refunds[idempotency_key] = result
        return result

    def get_refund(self, *, payment_ref, idempotency_key):
        if self.get_results:
            return self.get_results.pop(0)
        return self.refunds.get(idempotency_key)


class CrashAfterAcceptAdapter(FakeAdapter):
    """Records provider acceptance, then simulates a worker crash before the write."""

    def create_refund(self, *, payment_ref, amount_cents, currency, idempotency_key):
        super().create_refund(
            payment_ref=payment_ref,
            amount_cents=amount_cents,
            currency=currency,
            idempotency_key=idempotency_key,
        )
        raise RuntimeError("simulated worker crash after provider acceptance")


def _approve(session, case_id: int):
    reviewer = _user_id(session, "reviewer")
    return cases_service.approve(session, case_id=case_id, reviewer_id=reviewer, reason="ok")


def test_approval_writes_action_and_outbox_atomically(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    try:
        approved = _approve(session, case.id)
        assert approved.status == "APPROVED"

        action = session.execute(
            select(RefundAction).where(RefundAction.case_id == case.id)
        ).scalar_one()
        assert action.status == "PENDING"
        assert action.amount_cents == 7999
        assert action.currency == "usd"
        assert action.provider == "local"
        assert action.payment_ref == "local_pay_1"
        assert action.idempotency_key == f"refund-case-{case.id}"

        outbox = session.execute(select(OutboxEvent)).scalars().all()
        assert [e.event_type for e in outbox] == ["refund.approved"]
        assert outbox[0].status == "PENDING"

        transitions = [e.transition for e in approved.events]
        assert transitions == ["CREATED", "APPROVED"]
    finally:
        session.close()


def test_duplicate_job_delivery_executes_once(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = FakeAdapter()
    try:
        _approve(session, case.id)
        first = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        second = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert first.status == "SUCCEEDED"
        assert second.status == "SUCCEEDED"
        assert len(adapter.calls) == 1  # duplicate delivery did not resubmit

        events = session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id)).scalars().all()
        assert [e.transition for e in events].count("REFUNDED") == 1
        assert session.get(Case, case.id).status == "REFUNDED"
    finally:
        session.close()


def test_concurrent_approval_creates_one_action(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'approve.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    from src.backend.db import get_session_factory, init_db

    init_db(engine)
    factory = get_session_factory(engine)
    setup = factory()
    seed(setup)
    alice = _user_id(setup, "alice")
    case = cases_service.request_refund(setup, customer_id=alice, order_id=1001, reason="broken")
    case_id = case.id
    setup.close()

    errors = []

    def worker():
        session = factory()
        try:
            _approve(session, case_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    check = factory()
    actions = check.execute(select(RefundAction).where(RefundAction.case_id == case_id)).scalars().all()
    outbox = check.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == case_id)).scalars().all()
    events = check.execute(select(CaseEvent).where(CaseEvent.case_id == case_id)).scalars().all()
    check.close()
    assert len(actions) == 1
    assert len(outbox) == 1
    assert [e.transition for e in events].count("APPROVED") == 1
    engine.dispose()


def test_retryable_failure_requeues_then_succeeds(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = FakeAdapter()
    adapter.behaviors = [RetryableProviderError("temporary")]
    try:
        _approve(session, case.id)
        action = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert action.status == "RETRYABLE"
        assert session.get(Case, case.id).status == "PROCESSING"

        requeued = session.execute(select(OutboxEvent)).scalars().all()
        assert [e.status for e in requeued].count("PENDING") >= 1

        action = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert action.status == "SUCCEEDED"
        assert session.get(Case, case.id).status == "REFUNDED"
        assert len(adapter.calls) == 2
    finally:
        session.close()


def test_permanent_failure_surfaces_needs_attention(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = FakeAdapter()
    adapter.behaviors = [PermanentProviderError("declined")]
    try:
        _approve(session, case.id)
        action = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert action.status == "PERMANENT_FAILURE"
        assert session.get(Case, case.id).status == "NEEDS_ATTENTION"
        events = session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id)).scalars().all()
        assert "NEEDS_ATTENTION" in [e.transition for e in events]
        notifications = session.execute(select(Notification)).scalars().all()
        assert [n.kind for n in notifications] == ["refund.needs_attention"]
    finally:
        session.close()


def test_uncertain_reconcile_success(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = FakeAdapter()
    adapter.behaviors = [UncertainProviderError("timeout")]
    adapter.get_results = [
        RefundResult(status="succeeded", provider_refund_id="re_reconciled", amount_cents=7999, currency="usd")
    ]
    try:
        _approve(session, case.id)
        action = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert action.status == "SUCCEEDED"
        assert action.provider_refund_id == "re_reconciled"
        assert session.get(Case, case.id).status == "REFUNDED"
    finally:
        session.close()


def test_uncertain_reconcile_not_found_retries(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = FakeAdapter()
    adapter.behaviors = [UncertainProviderError("timeout")]
    adapter.get_results = [None]
    try:
        _approve(session, case.id)
        action = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert action.status == "RETRYABLE"
        assert session.get(Case, case.id).status == "PROCESSING"
    finally:
        session.close()


def test_uncertain_reconcile_ambiguous_needs_attention(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = FakeAdapter()
    adapter.behaviors = [UncertainProviderError("timeout")]
    adapter.get_results = [RefundResult(status="pending", provider_refund_id="re_pending")]
    try:
        _approve(session, case.id)
        action = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert action.status == "NEEDS_ATTENTION"
        assert session.get(Case, case.id).status == "NEEDS_ATTENTION"
    finally:
        session.close()


def test_worker_crash_after_provider_acceptance_recovers(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = CrashAfterAcceptAdapter()
    try:
        _approve(session, case.id)
        with pytest.raises(RuntimeError):
            refund_execution.execute_action(session, case_id=case.id, adapter=adapter)

        # The provider accepted, but the local write never happened.
        action = session.execute(select(RefundAction).where(RefundAction.case_id == case.id)).scalar_one()
        assert action.status == "SUBMITTING"
        assert action.provider_refund_id is None

        # Restart: reconciliation finds the accepted refund instead of resubmitting.
        recovered = refund_execution.execute_action(session, case_id=case.id, adapter=adapter)
        assert recovered.status == "SUCCEEDED"
        assert session.get(Case, case.id).status == "REFUNDED"
        events = session.execute(select(CaseEvent).where(CaseEvent.case_id == case.id)).scalars().all()
        assert [e.transition for e in events].count("REFUNDED") == 1
        assert len(adapter.calls) == 1
    finally:
        session.close()


def test_dispatcher_retries_unsent_outbox(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    try:
        _approve(session, case.id)
        event = session.execute(select(OutboxEvent)).scalar_one()

        def failing(_event):
            raise RuntimeError("broker unavailable")

        result = dispatch_pending(session, enqueue=failing)
        assert result["failed"] == 1
        session.refresh(event)
        assert event.status == "PENDING"
        assert event.attempts == 1

        delivered = []
        result = dispatch_pending(
            session, enqueue=delivered.append, now=utcnow() + timedelta(seconds=120)
        )
        session.refresh(event)
        assert result["sent"] == 1
        assert event.status == "SENT"
        assert len(delivered) == 1
    finally:
        session.close()


def test_dispatcher_recovers_stale_submitting_action(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    try:
        _approve(session, case.id)
        action = session.execute(select(RefundAction).where(RefundAction.case_id == case.id)).scalar_one()
        # Simulate: the approval's outbox record was dispatched, then the worker
        # crashed while SUBMITTING.
        original = session.execute(select(OutboxEvent)).scalar_one()
        original.status = "SENT"
        action.status = "SUBMITTING"
        action.updated_at = utcnow() - timedelta(seconds=3600)
        session.commit()

        requeued = refund_execution.recover_stale_actions(session, stale_after_seconds=60)
        assert requeued == 1
        pending = session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "refund.approved", OutboxEvent.status == "PENDING"
            )
        ).scalars().all()
        assert len(pending) == 1
    finally:
        session.close()
