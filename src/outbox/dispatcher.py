"""Outbox dispatcher.

The approval transaction writes a ``PENDING`` outbox row. This dispatcher scans
PENDING rows (re-dispatching them on every tick, so a crash between commit and
dispatch — or between dispatch and enqueue — is recovered automatically) and
turns them into Taskiq jobs. Rows that fail to enqueue keep their state with
backoff and are retried; after too many attempts they are marked FAILED.

Recovery of unsent records is therefore structural: nothing is deleted on
dispatch, and ``PENDING`` always means "must be re-enqueued".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from src.backend import constants as C
from src.backend.models import OutboxEvent, utcnow

logger = logging.getLogger("support_agent.outbox")

MAX_DISPATCH_ATTEMPTS = 8


def default_enqueue(event: OutboxEvent) -> None:
    """Route an outbox record to its Taskiq task (Redis broker in production)."""
    payload = event.payload or {}
    if event.event_type == C.OUTBOX_REFUND_APPROVED:
        from src.tasks.refund_tasks import execute_refund_task

        case_id = payload.get("case_id", event.aggregate_id)
        asyncio.run(execute_refund_task.kiq(case_id))
        return
    if event.event_type == C.OUTBOX_NOTIFICATION_SEND:
        from src.tasks.notification_tasks import send_notification_task

        notification_id = payload.get("notification_id", event.aggregate_id)
        asyncio.run(send_notification_task.kiq(notification_id))
        return
    raise ValueError(f"Unknown outbox event type: {event.event_type}")


def dispatch_pending(
    session, *, enqueue=None, limit: int = 50, now=None
) -> dict:
    enqueue = enqueue or default_enqueue
    now = now or utcnow()
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.status == C.OUTBOX_STATUS_PENDING,
            OutboxEvent.available_at <= now,
        )
        .order_by(OutboxEvent.id)
        .limit(limit)
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    events = list(session.execute(stmt).scalars())
    sent = 0
    failed = 0
    for event in events:
        try:
            enqueue(event)
        except Exception as exc:  # noqa: BLE001 - enqueue failures are retried
            event.attempts += 1
            event.last_error = type(exc).__name__
            backoff = min(300, 5 * (2 ** min(event.attempts, 6)))
            event.available_at = utcnow() + timedelta(seconds=backoff)
            if event.attempts >= MAX_DISPATCH_ATTEMPTS:
                event.status = C.OUTBOX_STATUS_FAILED
            failed += 1
            logger.warning("outbox_enqueue_failed event=%s (%s)", event.id, type(exc).__name__)
        else:
            event.status = C.OUTBOX_STATUS_SENT
            event.attempts += 1
            event.processed_at = utcnow()
            event.last_error = None
            sent += 1
    session.commit()
    return {"sent": sent, "failed": failed}


def recover_stale(session) -> int:
    """Re-enqueue refund actions stuck in SUBMITTING after a worker crash."""
    from src.services.refund_execution import recover_stale_actions

    return recover_stale_actions(session)
