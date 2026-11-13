"""Map ORM objects to customer-safe response models."""

from __future__ import annotations

from src.api.schemas import (
    CaseDetail,
    CaseEventOut,
    CaseOut,
    NotificationOut,
    OrderOut,
    OutboxOut,
    RefundActionOut,
    ReviewCaseDetail,
)
from src.backend.models import Case, Notification, OutboxEvent, RefundAction


def _execution_status(case: Case) -> str | None:
    action = case.refund_action
    return action.status if action is not None else None


def to_case_out(case: Case) -> CaseOut:
    return CaseOut(
        id=case.id,
        kind=case.kind,
        order_id=case.order_id,
        status=case.status,
        reason=case.reason,
        ticket_id=case.ticket_id,
        decision_reason=case.decision_reason,
        decided_at=case.decided_at,
        created_at=case.created_at,
        updated_at=case.updated_at,
        policy_version=case.policy_version,
        policy_document_id=case.policy_document_id,
        execution_status=_execution_status(case),
    )


def _events(case: Case) -> list[CaseEventOut]:
    return [
        CaseEventOut(
            id=event.id,
            transition=event.transition,
            reason=event.reason,
            created_at=event.created_at,
            actor_id=event.actor_id,
        )
        for event in (case.events or [])
    ]


def _order(case: Case) -> OrderOut | None:
    if case.order is None:
        return None
    return OrderOut(
        order_id=case.order.order_id,
        item=case.order.item,
        status=case.order.status,
        order_date=case.order.order_date.isoformat(),
        amount=case.order.amount,
    )


def to_case_detail(case: Case) -> CaseDetail:
    return CaseDetail(
        **to_case_out(case).model_dump(),
        events=_events(case),
        order=_order(case),
    )


def to_action_out(action: RefundAction) -> RefundActionOut:
    return RefundActionOut(
        id=action.id,
        status=action.status,
        provider=action.provider,
        provider_refund_id=action.provider_refund_id,
        payment_ref=action.payment_ref,
        amount_cents=action.amount_cents,
        currency=action.currency,
        attempts=action.attempts,
        last_error=action.last_error,
        idempotency_key=action.idempotency_key,
        processed_at=action.processed_at,
        created_at=action.created_at,
        updated_at=action.updated_at,
    )


def to_notification_out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        kind=notification.kind,
        status=notification.status,
        to_email=notification.to_email,
        attempts=notification.attempts,
        last_error=notification.last_error,
        created_at=notification.created_at,
        sent_at=notification.sent_at,
    )


def to_outbox_out(event: OutboxEvent) -> OutboxOut:
    return OutboxOut(
        id=event.id,
        event_type=event.event_type,
        status=event.status,
        attempts=event.attempts,
        last_error=event.last_error,
        available_at=event.available_at,
        processed_at=event.processed_at,
    )


def to_review_case_detail(
    case: Case, *, notifications: list[Notification], outbox: list[OutboxEvent]
) -> ReviewCaseDetail:
    return ReviewCaseDetail(
        **to_case_detail(case).model_dump(),
        action=to_action_out(case.refund_action) if case.refund_action is not None else None,
        notifications=[to_notification_out(n) for n in notifications],
        outbox=[to_outbox_out(e) for e in outbox],
    )
