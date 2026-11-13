"""Durable refund execution.

Approval is a single database transaction that writes:
  - the case transition PENDING_REVIEW -> APPROVED,
  - the APPROVED audit event,
  - the single ``RefundAction`` for the case (unique case_id + stable provider
    idempotency key),
  - the ``refund.approved`` outbox record.

The dispatcher turns outbox records into Taskiq jobs; workers call
``execute_action``. Execution is idempotent: a duplicate job delivery or a
worker crash after provider acceptance is reconciled against the provider rather
than resubmitted blindly. Ambiguous outcomes become NEEDS_ATTENTION.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, update

from src.backend import constants as C
from src.backend.models import (
    Case,
    CaseEvent,
    Notification,
    OutboxEvent,
    RefundAction,
    utcnow,
)
from src.integrations.commerce import LocalCommerceAdapter
from src.integrations.payments import (
    PaymentAdapter,
    PermanentProviderError,
    RetryableProviderError,
    RefundResult,
    UncertainProviderError,
    new_idempotency_key,
)
from src.services.exceptions import NotFound, Unprocessable
from src.services.notifications import enqueue_case_notification

logger = logging.getLogger("support_agent.refund_execution")

MAX_ACTION_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 5
STALE_SUBMITTING_SECONDS = 600


def _reload_case(session, case_id: int) -> Case:
    return session.execute(
        select(Case).where(Case.id == case_id).execution_options(populate_existing=True)
    ).scalar_one()


def _reload_action(session, action_id: int) -> RefundAction:
    return session.execute(
        select(RefundAction)
        .where(RefundAction.id == action_id)
        .execution_options(populate_existing=True)
    ).scalar_one()


def _notify_needs_attention(session, case: Case, reason: str) -> None:
    enqueue_case_notification(
        session,
        case=case,
        kind=C.NOTIFICATION_KIND_NEEDS_ATTENTION,
        subject=f"We need more time on your refund (case #{case.id})",
        body=(
            f"Hello,\n\nYour refund request (case #{case.id}) needs a manual review "
            f"before it can be completed. Our team has been notified.\n\n"
            f"Reference: {reason}\n\nCommerce Support"
        ),
    )


def _set_case_status(
    session,
    case: Case,
    status: str,
    transition: str,
    reason: str,
    *,
    allowed_from: tuple[str, ...],
    notify_attention: bool = False,
) -> bool:
    changed = session.execute(
        update(Case)
        .where(Case.id == case.id, Case.status.in_(allowed_from))
        .values(status=status)
    ).rowcount
    if not changed:
        return False
    session.add(CaseEvent(case_id=case.id, transition=transition, reason=reason))
    if notify_attention:
        _notify_needs_attention(session, case, reason)
    return True


def _mark_needs_attention(session, action: RefundAction, reason: str) -> RefundAction:
    session.execute(
        update(RefundAction)
        .where(RefundAction.id == action.id)
        .values(status=C.ACTION_STATUS_NEEDS_ATTENTION, last_error=reason)
    )
    session.commit()
    case = session.get(Case, action.case_id)
    _set_case_status(
        session,
        case,
        C.CASE_STATUS_NEEDS_ATTENTION,
        C.TRANSITION_NEEDS_ATTENTION,
        reason,
        allowed_from=(C.CASE_STATUS_APPROVED, C.CASE_STATUS_PROCESSING),
        notify_attention=True,
    )
    session.commit()
    return _reload_action(session, action.id)


def _mark_refunded(session, action: RefundAction, result: RefundResult) -> RefundAction:
    provider_refund_id = result.provider_refund_id or action.provider_refund_id
    session.execute(
        update(RefundAction)
        .where(RefundAction.id == action.id)
        .values(
            status=C.ACTION_STATUS_SUCCEEDED,
            provider_refund_id=provider_refund_id,
            processed_at=utcnow(),
            last_error=None,
        )
    )
    session.commit()
    case = session.get(Case, action.case_id)
    changed = _set_case_status(
        session,
        case,
        C.CASE_STATUS_REFUNDED,
        C.TRANSITION_REFUNDED,
        f"Refund {provider_refund_id or ''} confirmed by {action.provider}.".strip(),
        allowed_from=(
            C.CASE_STATUS_APPROVED,
            C.CASE_STATUS_PROCESSING,
            C.CASE_STATUS_NEEDS_ATTENTION,
        ),
    )
    if changed:
        enqueue_case_notification(
            session,
            case=case,
            kind=C.NOTIFICATION_KIND_REFUND_COMPLETED,
            subject=f"Your refund was completed (case #{case.id})",
            body=(
                f"Hello,\n\nYour refund for case #{case.id} has been completed and sent "
                f"to your original payment method.\n\nCommerce Support"
            ),
        )
    session.commit()
    return _reload_action(session, action.id)


def _handle_permanent(session, action: RefundAction, reason: str) -> RefundAction:
    # Keep the action's terminal PERMANENT_FAILURE status; the case moves to
    # NEEDS_ATTENTION so a reviewer can see and handle it.
    session.execute(
        update(RefundAction)
        .where(RefundAction.id == action.id)
        .values(
            status=C.ACTION_STATUS_PERMANENT_FAILURE,
            last_error=reason,
            processed_at=utcnow(),
        )
    )
    session.commit()
    case = session.get(Case, action.case_id)
    _set_case_status(
        session,
        case,
        C.CASE_STATUS_NEEDS_ATTENTION,
        C.TRANSITION_NEEDS_ATTENTION,
        reason,
        allowed_from=(C.CASE_STATUS_APPROVED, C.CASE_STATUS_PROCESSING),
        notify_attention=True,
    )
    session.commit()
    return _reload_action(session, action.id)


def _handle_retryable(session, action: RefundAction, reason: str) -> RefundAction:
    if action.attempts >= MAX_ACTION_ATTEMPTS:
        return _mark_needs_attention(session, action, f"Retries exhausted: {reason}")

    session.execute(
        update(RefundAction)
        .where(RefundAction.id == action.id)
        .values(status=C.ACTION_STATUS_RETRYABLE, last_error=reason)
    )
    backoff = RETRY_BACKOFF_SECONDS * max(1, action.attempts)
    session.add(
        OutboxEvent(
            event_type=C.OUTBOX_REFUND_APPROVED,
            aggregate_type="case",
            aggregate_id=action.case_id,
            payload={"case_id": action.case_id, "action_id": action.id, "retry": True},
            status=C.OUTBOX_STATUS_PENDING,
            available_at=utcnow() + timedelta(seconds=backoff),
        )
    )
    session.commit()
    return _reload_action(session, action.id)


def _reconcile(adapter: PaymentAdapter, action: RefundAction) -> RefundResult | None:
    try:
        return adapter.get_refund(
            payment_ref=action.payment_ref or "", idempotency_key=action.idempotency_key
        )
    except Exception:  # noqa: BLE001 - reconciliation is best-effort
        return None


def _handle_uncertain(
    session, action: RefundAction, adapter: PaymentAdapter, reason: str
) -> RefundAction:
    session.execute(
        update(RefundAction)
        .where(RefundAction.id == action.id)
        .values(status=C.ACTION_STATUS_UNCERTAIN, last_error=reason)
    )
    session.commit()
    action = _reload_action(session, action.id)

    reconciled = _reconcile(adapter, action)
    if reconciled is None:
        # Not found at the provider: the stable idempotency key makes a retry safe.
        return _handle_retryable(session, action, f"uncertain; not found at provider: {reason}")
    if reconciled.status == "succeeded":
        return _mark_refunded(session, action, reconciled)
    if reconciled.status == "failed":
        return _handle_permanent(
            session, action, reconciled.failure_reason or "Provider declined the refund."
        )
    return _mark_needs_attention(session, action, f"Ambiguous provider outcome: {reason}")


def _apply_result(
    session, action: RefundAction, result: RefundResult, adapter: PaymentAdapter
) -> RefundAction:
    if result.status == "succeeded":
        return _mark_refunded(session, action, result)
    if result.status == "failed":
        return _handle_permanent(
            session, action, result.failure_reason or "Provider declined the refund."
        )
    if result.status == "pending":
        session.execute(
            update(RefundAction)
            .where(RefundAction.id == action.id)
            .values(
                status=C.ACTION_STATUS_SUBMITTING,
                provider_refund_id=result.provider_refund_id or action.provider_refund_id,
                last_error=None,
            )
        )
        session.commit()
        return _reload_action(session, action.id)
    return _handle_uncertain(session, action, adapter, "Provider returned an unknown status.")


def _create_action(session, case: Case) -> RefundAction | None:
    snapshot = LocalCommerceAdapter(session).get_order(case.order_id) if case.order_id else None
    if snapshot is None:
        _set_case_status(
            session,
            case,
            C.CASE_STATUS_NEEDS_ATTENTION,
            C.TRANSITION_NEEDS_ATTENTION,
            "Order data could not be verified; refund cannot be executed automatically.",
            allowed_from=(C.CASE_STATUS_APPROVED,),
            notify_attention=True,
        )
        return None
    if snapshot.customer_id != case.customer_id:
        _set_case_status(
            session,
            case,
            C.CASE_STATUS_NEEDS_ATTENTION,
            C.TRANSITION_NEEDS_ATTENTION,
            "Order ownership could not be verified; refund cannot be executed automatically.",
            allowed_from=(C.CASE_STATUS_APPROVED,),
            notify_attention=True,
        )
        return None
    if not snapshot.provider_payment_id:
        _set_case_status(
            session,
            case,
            C.CASE_STATUS_NEEDS_ATTENTION,
            C.TRANSITION_NEEDS_ATTENTION,
            "Payment reference is missing; refund needs manual attention.",
            allowed_from=(C.CASE_STATUS_APPROVED,),
            notify_attention=True,
        )
        return None

    amount_cents = round((snapshot.payment_amount if snapshot.payment_amount is not None else snapshot.amount) * 100)
    action = RefundAction(
        case_id=case.id,
        order_id=snapshot.order_id,
        customer_id=case.customer_id,
        payment_id=snapshot.payment_id,
        provider=snapshot.provider or "local",
        payment_ref=snapshot.provider_payment_id,
        amount_cents=amount_cents,
        currency=snapshot.currency,
        idempotency_key=new_idempotency_key(case.id),
        status=C.ACTION_STATUS_PENDING,
    )
    session.add(action)
    session.flush()
    session.add(
        OutboxEvent(
            event_type=C.OUTBOX_REFUND_APPROVED,
            aggregate_type="case",
            aggregate_id=case.id,
            payload={"case_id": case.id, "action_id": action.id},
            status=C.OUTBOX_STATUS_PENDING,
        )
    )
    return action


def approve_with_action(
    session, *, case_id: int, reviewer_id: int, reason: str | None
) -> Case:
    """Approve a refund case and create its action + outbox record atomically."""
    case = session.get(Case, case_id)
    if case is None:
        raise NotFound(f"No case found with id {case_id}.")
    if case.kind != C.CASE_KIND_REFUND:
        raise Unprocessable("Only refund cases can be approved or rejected.")

    won = session.execute(
        update(Case)
        .where(Case.id == case_id, Case.status == C.CASE_STATUS_PENDING_REVIEW)
        .values(
            status=C.CASE_STATUS_APPROVED,
            decided_by=reviewer_id,
            decided_at=utcnow(),
            decision_reason=reason,
        )
    ).rowcount
    if won == 0:
        session.rollback()
        return _reload_case(session, case_id)

    session.add(CaseEvent(case_id=case_id, transition=C.TRANSITION_APPROVED, actor_id=reviewer_id, reason=reason))

    existing_action = session.execute(
        select(RefundAction).where(RefundAction.case_id == case_id)
    ).scalar_one_or_none()
    if existing_action is None and case.order_id is not None:
        _create_action(session, case)

    session.commit()
    return _reload_case(session, case_id)


def execute_action(
    session, *, case_id: int, adapter: PaymentAdapter
) -> RefundAction | None:
    """Execute the case's single refund action, idempotently.

    Returns the current action state. Unexpected exceptions (e.g. a simulated
    process crash) propagate and leave the action in SUBMITTING for recovery.
    """
    action = session.execute(
        select(RefundAction).where(RefundAction.case_id == case_id)
    ).scalar_one_or_none()
    if action is None:
        return None
    if action.status in (
        C.ACTION_STATUS_SUCCEEDED,
        C.ACTION_STATUS_PERMANENT_FAILURE,
        C.ACTION_STATUS_NEEDS_ATTENTION,
    ):
        return action
    if not action.payment_ref:
        return _mark_needs_attention(session, action, "Payment reference is missing at execution time.")

    claimed = session.execute(
        update(RefundAction)
        .where(
            RefundAction.id == action.id,
            RefundAction.status.in_([C.ACTION_STATUS_PENDING, C.ACTION_STATUS_RETRYABLE]),
        )
        .values(
            status=C.ACTION_STATUS_SUBMITTING,
            attempts=RefundAction.attempts + 1,
            updated_at=utcnow(),
        )
    ).rowcount
    session.commit()
    action = _reload_action(session, action.id)

    if claimed == 0:
        if action.status in (
            C.ACTION_STATUS_SUCCEEDED,
            C.ACTION_STATUS_PERMANENT_FAILURE,
            C.ACTION_STATUS_NEEDS_ATTENTION,
        ):
            return action
        # Duplicate delivery or recovery after a crash: reconcile before resubmitting.
        reconciled = _reconcile(adapter, action)
        if reconciled is not None:
            return _apply_result(session, action, reconciled, adapter)

    # Move the case into PROCESSING once execution actually starts.
    case = session.get(Case, action.case_id)
    changed = session.execute(
        update(Case)
        .where(Case.id == case.id, Case.status.in_([C.CASE_STATUS_APPROVED, C.CASE_STATUS_NEEDS_ATTENTION]))
        .values(status=C.CASE_STATUS_PROCESSING)
    ).rowcount
    if changed:
        session.add(
            CaseEvent(
                case_id=case.id,
                transition=C.TRANSITION_PROCESSING,
                reason="Refund execution started.",
            )
        )
    session.commit()

    try:
        result = adapter.create_refund(
            payment_ref=action.payment_ref,
            amount_cents=action.amount_cents,
            currency=action.currency,
            idempotency_key=action.idempotency_key,
        )
    except UncertainProviderError as exc:
        return _handle_uncertain(session, action, adapter, str(exc))
    except RetryableProviderError as exc:
        return _handle_retryable(session, action, str(exc))
    except PermanentProviderError as exc:
        return _handle_permanent(session, action, str(exc))
    except Exception:
        # Simulated crash / unexpected error: leave SUBMITTING for reconciliation.
        raise

    return _apply_result(session, action, result, adapter)


def recover_stale_actions(
    session, *, stale_after_seconds: int = STALE_SUBMITTING_SECONDS, limit: int = 100
) -> int:
    """Re-enqueue actions stuck in SUBMITTING (e.g. a crashed worker)."""
    cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
    stale = list(
        session.execute(
            select(RefundAction)
            .where(RefundAction.status == C.ACTION_STATUS_SUBMITTING, RefundAction.updated_at < cutoff)
            .limit(limit)
        ).scalars()
    )
    requeued = 0
    for action in stale:
        already = session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == C.OUTBOX_REFUND_APPROVED,
                OutboxEvent.status == C.OUTBOX_STATUS_PENDING,
                OutboxEvent.aggregate_id == action.case_id,
            )
        ).scalar_one_or_none()
        if already is None:
            session.add(
                OutboxEvent(
                    event_type=C.OUTBOX_REFUND_APPROVED,
                    aggregate_type="case",
                    aggregate_id=action.case_id,
                    payload={"case_id": action.case_id, "action_id": action.id, "recovery": True},
                    status=C.OUTBOX_STATUS_PENDING,
                )
            )
            requeued += 1
    session.commit()
    return requeued


def list_notifications(session, *, case_id: int) -> list[Notification]:
    return list(
        session.execute(
            select(Notification).where(Notification.case_id == case_id).order_by(Notification.id)
        ).scalars()
    )


def list_outbox_for_case(session, *, case_id: int) -> list[OutboxEvent]:
    return list(
        session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.aggregate_type == "case", OutboxEvent.aggregate_id == case_id)
            .order_by(OutboxEvent.id)
        ).scalars()
    )
