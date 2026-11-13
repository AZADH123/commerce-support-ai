from sqlalchemy import select

from src.backend import db
from src.backend.models import Notification, OutboxEvent, User
from src.backend.seed import DEMO_SUBS
from src.integrations.email import InMemoryEmailAdapter, RetryableEmailError
from src.integrations.payments import LocalPaymentAdapter
from src.services import cases as cases_service
from src.services import refund_execution
from src.services.notifications import send_notification


def _user_id(session, key: str) -> int:
    return session.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one().id


class RetryableEmailAdapter:
    def send(self, *, to_email, subject, body):
        raise RetryableEmailError("smtp down")


class PermanentEmailAdapter:
    def send(self, *, to_email, subject, body):
        raise ValueError("bad address")


def _complete_refund(session, case_id: int):
    cases_service.approve(
        session, case_id=case_id, reviewer_id=_user_id(session, "reviewer"), reason="ok"
    )
    return refund_execution.execute_action(
        session, case_id=case_id, adapter=LocalPaymentAdapter()
    )


def test_refund_success_creates_durable_notification(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    try:
        _complete_refund(session, case.id)
        notification = session.execute(select(Notification)).scalar_one()
        assert notification.kind == "refund.completed"
        assert notification.status == "PENDING"
        assert notification.to_email == "alice@example.com"

        notification_outbox = session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "notification.send")
        ).scalars().all()
        assert len(notification_outbox) == 1
        assert notification_outbox[0].payload["notification_id"] == notification.id
    finally:
        session.close()


def test_send_notification_marks_sent_and_is_retry_safe(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    adapter = InMemoryEmailAdapter()
    try:
        _complete_refund(session, case.id)
        notification = session.execute(select(Notification)).scalar_one()
        first = send_notification(session, notification_id=notification.id, adapter=adapter)
        assert first.status == "SENT"
        assert first.provider_message_id

        second = send_notification(session, notification_id=notification.id, adapter=adapter)
        assert second.status == "SENT"
        assert len(adapter.sent) == 1  # duplicate job delivery did not double-send
    finally:
        session.close()


def test_retryable_delivery_failure_stays_pending(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    try:
        _complete_refund(session, case.id)
        notification = session.execute(select(Notification)).scalar_one()

        failed = send_notification(
            session, notification_id=notification.id, adapter=RetryableEmailAdapter()
        )
        assert failed.status == "PENDING"
        assert failed.attempts == 1
        assert failed.last_error == "smtp down"

        sent = send_notification(
            session, notification_id=notification.id, adapter=InMemoryEmailAdapter()
        )
        assert sent.status == "SENT"
    finally:
        session.close()


def test_permanent_delivery_failure_is_terminal(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    session = db.get_session()
    try:
        _complete_refund(session, case.id)
        notification = session.execute(select(Notification)).scalar_one()
        failed = send_notification(
            session, notification_id=notification.id, adapter=PermanentEmailAdapter()
        )
        assert failed.status == "FAILED"
        assert failed.last_error == "ValueError"
    finally:
        session.close()
