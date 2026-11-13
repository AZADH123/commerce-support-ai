"""Durable customer notifications.

Every case update is recorded as a ``Notification`` row (the durable delivery
record) plus an outbox event, then sent by the notification worker. Retries are
safe: a send is claimed with a status CAS, and an already-SENT notification is
never sent again.
"""

from __future__ import annotations

from sqlalchemy import select, update

from src.backend import constants as C
from src.backend.models import Case, Notification, OutboxEvent, User, utcnow
from src.integrations.email import EmailAdapter, RetryableEmailError
from src.services.exceptions import NotFound


def enqueue_case_notification(
    session, *, case: Case, kind: str, subject: str, body: str
) -> Notification:
    customer = session.get(User, case.customer_id)
    notification = Notification(
        case_id=case.id,
        customer_id=case.customer_id,
        kind=kind,
        channel="email",
        to_email=customer.email if customer else None,
        subject=subject,
        body=body,
        status=C.NOTIFICATION_STATUS_PENDING,
    )
    session.add(notification)
    session.flush()
    session.add(
        OutboxEvent(
            event_type=C.OUTBOX_NOTIFICATION_SEND,
            aggregate_type="notification",
            aggregate_id=notification.id,
            payload={"notification_id": notification.id, "case_id": case.id},
            status=C.OUTBOX_STATUS_PENDING,
        )
    )
    return notification


def send_notification(session, *, notification_id: int, adapter: EmailAdapter) -> Notification:
    notification = session.get(Notification, notification_id)
    if notification is None:
        raise NotFound(f"No notification found with id {notification_id}.")

    if notification.status == C.NOTIFICATION_STATUS_SENT:
        return notification

    claimed = session.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.status.in_(
                [C.NOTIFICATION_STATUS_PENDING, C.NOTIFICATION_STATUS_FAILED]
            ),
        )
        .values(
            status=C.NOTIFICATION_STATUS_SENDING,
            attempts=Notification.attempts + 1,
        )
    ).rowcount
    session.commit()
    notification = session.execute(
        select(Notification)
        .where(Notification.id == notification_id)
        .execution_options(populate_existing=True)
    ).scalar_one()

    if claimed == 0:
        # Already SENT, or another worker is mid-send. Never double-send.
        return notification

    try:
        message_id = adapter.send(
            to_email=notification.to_email or "",
            subject=notification.subject,
            body=notification.body,
        )
    except RetryableEmailError as exc:
        notification.status = C.NOTIFICATION_STATUS_PENDING
        notification.last_error = str(exc)
        session.commit()
        return notification
    except Exception as exc:  # noqa: BLE001 - permanent failure for this channel
        notification.status = C.NOTIFICATION_STATUS_FAILED
        notification.last_error = type(exc).__name__
        session.commit()
        return notification

    notification.status = C.NOTIFICATION_STATUS_SENT
    notification.provider_message_id = message_id
    notification.sent_at = utcnow()
    notification.last_error = None
    session.commit()
    return notification
