"""Provider webhook reconciliation.

Rules:
- Event ids are deduplicated by ``(provider, event_id)`` unique constraint.
- The provider action, payment reference, amount, and currency are validated
  against the trusted ``RefundAction`` before any transition.
- Late, duplicated, and out-of-order events never regress a finalized
  (REFUNDED/REJECTED) case; a late success may still recover NEEDS_ATTENTION.
- Every reconciled result is persisted with an audit event.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.backend import constants as C
from src.backend.models import Case, CaseEvent, RefundAction, WebhookEvent, utcnow
from src.services.notifications import enqueue_case_notification

logger = logging.getLogger("support_agent.webhooks")


def _find_action(session, provider: str, provider_refund_id: str | None, payment_ref: str | None) -> RefundAction | None:
    if provider_refund_id:
        action = session.execute(
            select(RefundAction).where(
                RefundAction.provider == provider,
                RefundAction.provider_refund_id == provider_refund_id,
            )
        ).scalar_one_or_none()
        if action is not None:
            return action
    if payment_ref:
        return session.execute(
            select(RefundAction).where(
                RefundAction.provider == provider,
                RefundAction.payment_ref == payment_ref,
            )
        ).scalar_one_or_none()
    return None


def _validate(action: RefundAction, *, provider: str, payment_ref: str | None, amount_cents: int | None, currency: str | None) -> str | None:
    if action.provider != provider:
        return "provider mismatch"
    if payment_ref and action.payment_ref != payment_ref:
        return "payment reference mismatch"
    if amount_cents is not None and action.amount_cents != amount_cents:
        return "amount mismatch"
    if currency and action.currency.lower() != currency.lower():
        return "currency mismatch"
    return None


def _apply_success(session, action: RefundAction, provider_refund_id: str | None, reason: str) -> bool:
    case = session.get(Case, action.case_id)
    if case is None or case.status in (C.CASE_STATUS_REFUNDED, C.CASE_STATUS_REJECTED):
        # Finalized: never regress or duplicate a completed result.
        return False
    action.status = C.ACTION_STATUS_SUCCEEDED
    action.provider_refund_id = provider_refund_id or action.provider_refund_id
    action.processed_at = utcnow()
    action.last_error = None
    case.status = C.CASE_STATUS_REFUNDED
    session.add(
        CaseEvent(
            case_id=case.id,
            transition=C.TRANSITION_REFUNDED,
            reason=reason,
        )
    )
    enqueue_case_notification(
        session,
        case=case,
        kind=C.NOTIFICATION_KIND_REFUND_COMPLETED,
        subject=f"Your refund was completed (case #{case.id})",
        body=(
            f"Hello,\n\nYour refund for case #{case.id} has been completed and sent to your "
            f"original payment method.\n\nCommerce Support"
        ),
    )
    return True


def _apply_failure(session, action: RefundAction, reason: str) -> bool:
    case = session.get(Case, action.case_id)
    if case is None or case.status in (C.CASE_STATUS_REFUNDED, C.CASE_STATUS_REJECTED):
        return False
    action.status = C.ACTION_STATUS_PERMANENT_FAILURE
    action.last_error = reason
    action.processed_at = utcnow()
    case.status = C.CASE_STATUS_NEEDS_ATTENTION
    session.add(
        CaseEvent(
            case_id=case.id,
            transition=C.TRANSITION_NEEDS_ATTENTION,
            reason=f"Provider reported failure: {reason}",
        )
    )
    enqueue_case_notification(
        session,
        case=case,
        kind=C.NOTIFICATION_KIND_NEEDS_ATTENTION,
        subject=f"We need more time on your refund (case #{case.id})",
        body=(
            f"Hello,\n\nThere was a problem completing your refund (case #{case.id}). "
            f"Our team has been notified and will follow up.\n\nCommerce Support"
        ),
    )
    return True


def process_event(session, *, provider: str, event: dict) -> WebhookEvent:
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "unknown")

    if not event_id:
        record = WebhookEvent(provider=provider, event_id="", event_type=event_type, status=C.WEBHOOK_STATUS_INVALID)
        session.add(record)
        session.commit()
        return record

    existing = session.execute(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider, WebhookEvent.event_id == event_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Duplicate delivery: acknowledge without re-applying.
        return existing

    record = WebhookEvent(
        provider=provider,
        event_id=event_id,
        event_type=event_type,
        status=C.WEBHOOK_STATUS_RECEIVED,
        payload=event,
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return session.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == provider, WebhookEvent.event_id == event_id
            )
        ).scalar_one()

    try:
        _apply(session, record, provider, event_type, event)
    except Exception as exc:  # noqa: BLE001 - persist the failure, never crash the receiver
        record.status = C.WEBHOOK_STATUS_INVALID
        record.error = type(exc).__name__
        logger.warning("webhook_processing_failed event=%s (%s)", event_id, type(exc).__name__)

    record.processed_at = utcnow()
    session.commit()
    return record


def _apply(session, record: WebhookEvent, provider: str, event_type: str, event: dict) -> None:
    obj = (event.get("data") or {}).get("object") or {}

    if event_type == "charge.refunded":
        refunds = (obj.get("refunds") or {}).get("data") or []
        if not refunds:
            record.status = C.WEBHOOK_STATUS_IGNORED
            return
        obj = refunds[0]

    if event_type not in ("refund.succeeded", "refund.failed", "refund.updated", "charge.refunded"):
        record.status = C.WEBHOOK_STATUS_IGNORED
        return

    provider_refund_id = obj.get("id")
    payment_ref = obj.get("payment_intent") or obj.get("charge")
    amount_cents = obj.get("amount")
    currency = obj.get("currency")
    provider_status = obj.get("status")
    refund_status = "succeeded" if event_type in ("refund.succeeded", "charge.refunded") else provider_status

    action = _find_action(session, provider, provider_refund_id, payment_ref)
    if action is None:
        record.status = C.WEBHOOK_STATUS_UNMATCHED
        record.error = "No refund action matched this event."
        return

    mismatch = _validate(
        action,
        provider=provider,
        payment_ref=payment_ref,
        amount_cents=amount_cents,
        currency=currency,
    )
    if mismatch:
        case = session.get(Case, action.case_id)
        if case is not None and case.status not in (C.CASE_STATUS_REFUNDED, C.CASE_STATUS_REJECTED):
            case.status = C.CASE_STATUS_NEEDS_ATTENTION
            session.add(
                CaseEvent(
                    case_id=case.id,
                    transition=C.TRANSITION_NEEDS_ATTENTION,
                    reason=f"Provider event did not match the authorized refund ({mismatch}).",
                )
            )
        record.status = C.WEBHOOK_STATUS_PROCESSED
        record.error = mismatch
        return

    if refund_status == "succeeded":
        applied = _apply_success(session, action, provider_refund_id, "Provider confirmed the refund.")
        record.status = C.WEBHOOK_STATUS_PROCESSED if applied else C.WEBHOOK_STATUS_IGNORED
        return
    if refund_status == "failed":
        applied = _apply_failure(session, action, "Provider reported the refund failed.")
        record.status = C.WEBHOOK_STATUS_PROCESSED if applied else C.WEBHOOK_STATUS_IGNORED
        return

    # pending / requires_action / unknown: no state regression, acknowledge.
    record.status = C.WEBHOOK_STATUS_IGNORED
