"""Escalation persistence: record human-escalation cases reviewers can find."""

from __future__ import annotations

import uuid

from src.backend import constants as C
from src.backend.models import Case, CaseEvent


def escalate(
    session,
    *,
    customer_id: int | None,
    order_id: int | None = None,
    reason: str,
    context: str = "",
) -> Case:
    """Create an OPEN escalation case with a stable ticket reference."""
    ticket_id = uuid.uuid4().hex[:8]
    case = Case(
        kind=C.CASE_KIND_ESCALATION,
        customer_id=customer_id,
        order_id=order_id,
        status=C.CASE_STATUS_OPEN,
        reason=reason,
        ticket_id=ticket_id,
    )
    note = (reason if not context else f"{reason} | {context}")[:2000]
    case.events.append(
        CaseEvent(transition=C.TRANSITION_ESCALATED, actor_id=customer_id, reason=note)
    )
    session.add(case)
    session.commit()
    return case
