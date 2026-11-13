"""Refund-case business rules: request, approve, reject, and lookups.

Ownership and transition rules live here so the API and the agent tools share
exactly one implementation. State machine for refund cases:

    (request_refund)                (reviewer approve)            (reviewer reject)
    [none]  ------>  PENDING_REVIEW  ----------------->  APPROVED  |
                     PENDING_REVIEW  ---------------------------------->  REJECTED

A refund case ends Phase 1 at APPROVED or REJECTED (no automatic payment).
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.backend import constants as C
from src.backend.models import Case, CaseEvent, Order, User, utcnow
from src.services.exceptions import Conflict, Forbidden, NotFound, Unprocessable

# Case statuses a customer may list/search and a reviewer may queue.
REVIEWABLE_STATUSES = (C.CASE_STATUS_PENDING_REVIEW,)


def _refund_case_for_order(session, order_id: int) -> Case | None:
    return session.execute(
        select(Case).where(Case.kind == C.CASE_KIND_REFUND, Case.order_id == order_id)
    ).scalar_one_or_none()


def request_refund(session, *, customer_id: int, order_id: int, reason: str) -> Case:
    """Create a PENDING_REVIEW refund case for the customer's own eligible order.

    Enforces, in order: order exists, order is owned by the customer, order is
    delivered (eligible), and no refund case already exists. The partial unique
    index ``uq_case_active_refund`` makes the no-duplicate rule hold even when
    two requests race past the pre-check.
    """
    order = session.get(Order, order_id)
    if order is None:
        raise NotFound(f"No order found with id {order_id}.")
    if order.customer_id != customer_id:
        raise Forbidden("Order does not belong to the authenticated customer.")
    if order.status != C.ORDER_DELIVERED:
        raise Unprocessable(
            f"Order status is '{order.status}'; only delivered orders are refund-eligible."
        )

    existing = _refund_case_for_order(session, order_id)
    if existing is not None:
        raise Conflict(f"A refund case for this order already exists with status '{existing.status}'.")

    case = Case(
        kind=C.CASE_KIND_REFUND,
        customer_id=customer_id,
        order_id=order_id,
        status=C.CASE_STATUS_PENDING_REVIEW,
        reason=reason,
    )
    case.events.append(
        CaseEvent(transition=C.TRANSITION_CREATED, actor_id=customer_id, reason=reason)
    )
    _record_policy_version(session, case)
    session.add(case)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise Conflict("A refund request for this order is already pending review.") from None
    return case


def _record_policy_version(session, case: Case) -> None:
    """Record the active refund policy version that informed the request."""
    try:
        from src.knowledge.policies import active_document

        document = active_document(session, store="default", topic=C.POLICY_TOPIC_REFUND)
        if document is not None:
            case.policy_document_id = document.id
            case.policy_version = document.version
    except Exception:  # noqa: BLE001 - policy provenance must never block a request
        pass


def decide(session, *, case_id: int, reviewer_id: int, decision: str, reason: str | None) -> Case:
    """Approve or reject a refund case.

    Approval delegates to the execution service so the APPROVED transition, the
    refund action, and the outbox record commit in one transaction. Rejection is
    a compare-and-swap transition that is idempotent under repeats and races.
    """
    if decision == C.CASE_STATUS_APPROVED:
        from src.services.refund_execution import approve_with_action

        return approve_with_action(
            session, case_id=case_id, reviewer_id=reviewer_id, reason=reason
        )

    case = session.get(Case, case_id)
    if case is None:
        raise NotFound(f"No case found with id {case_id}.")
    if case.kind != C.CASE_KIND_REFUND:
        raise Unprocessable("Only refund cases can be approved or rejected.")

    result = session.execute(
        update(Case)
        .where(Case.id == case_id, Case.status == C.CASE_STATUS_PENDING_REVIEW)
        .values(
            status=decision,
            decided_by=reviewer_id,
            decided_at=utcnow(),
            decision_reason=reason,
        )
    )
    if result.rowcount == 0:
        # Another request already decided this case (or this is a repeat).
        session.rollback()
        return session.execute(
            select(Case).where(Case.id == case_id).execution_options(populate_existing=True)
        ).scalar_one()

    session.add(CaseEvent(case_id=case_id, transition=decision, actor_id=reviewer_id, reason=reason))
    session.commit()
    session.expire_all()
    return session.execute(
        select(Case).where(Case.id == case_id).execution_options(populate_existing=True)
    ).scalar_one()


def approve(session, *, case_id: int, reviewer_id: int, reason: str | None) -> Case:
    from src.services.refund_execution import approve_with_action

    return approve_with_action(
        session, case_id=case_id, reviewer_id=reviewer_id, reason=reason
    )


def reject(session, *, case_id: int, reviewer_id: int, reason: str | None) -> Case:
    return decide(
        session,
        case_id=case_id,
        reviewer_id=reviewer_id,
        decision=C.CASE_STATUS_REJECTED,
        reason=reason,
    )


def get_case_for_customer(session, *, case_id: int, customer_id: int) -> Case:
    case = session.execute(
        select(Case).where(Case.id == case_id, Case.customer_id == customer_id)
    ).scalar_one_or_none()
    if case is None:
        raise NotFound(f"No case found with id {case_id}.")
    return case


def list_cases_for_customer(session, *, customer_id: int, status: str | None = None):
    stmt = select(Case).where(Case.customer_id == customer_id).order_by(Case.created_at.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    return list(session.execute(stmt).scalars())


def list_cases_for_reviewer(
    session,
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """Reviewer queue, newest first, with optional filters and pagination."""
    stmt = select(Case).order_by(Case.created_at.desc())
    if status:
        stmt = stmt.where(Case.status == status)
    if kind:
        stmt = stmt.where(Case.kind == kind)
    # Count independently so pagination metadata is accurate.
    count_stmt = select(Case)
    if status:
        count_stmt = count_stmt.where(Case.status == status)
    if kind:
        count_stmt = count_stmt.where(Case.kind == kind)
    total_count = len(list(session.execute(count_stmt).scalars()))
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars())
    return items, total_count
