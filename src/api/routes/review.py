"""Reviewer queue and decision endpoints (reviewer-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_db, require_reviewer
from src.api.schemas import DecisionRequest, PaginatedCases, ReviewCaseDetail
from src.api.serializers import to_case_out, to_review_case_detail
from src.backend.models import Case
from src.context import Principal
from src.services import cases as cases_service
from src.services import refund_execution as execution_service

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/cases", response_model=PaginatedCases)
def review_queue(
    status: str | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _reviewer: Principal = Depends(require_reviewer),
    session=Depends(get_db),
):
    items, total = cases_service.list_cases_for_reviewer(
        session, status=status, kind=kind, limit=limit, offset=offset
    )
    return PaginatedCases(
        items=[to_case_out(case) for case in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _detail(session, case: Case) -> ReviewCaseDetail:
    notifications = execution_service.list_notifications(session, case_id=case.id)
    outbox = execution_service.list_outbox_for_case(session, case_id=case.id)
    return to_review_case_detail(case, notifications=notifications, outbox=outbox)


@router.get("/cases/{case_id}", response_model=ReviewCaseDetail)
def review_case_detail(
    case_id: int,
    _reviewer: Principal = Depends(require_reviewer),
    session=Depends(get_db),
):
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case found with id {case_id}.")
    return _detail(session, case)


def _decide(case_id: int, decision: str, req: DecisionRequest, reviewer: Principal, session):
    if decision == "REJECTED" and not (req.reason or "").strip():
        raise HTTPException(status_code=422, detail="A reason is required to reject a case.")
    case = cases_service.decide(
        session,
        case_id=case_id,
        reviewer_id=reviewer.user_id,
        decision=decision,
        reason=req.reason,
    )
    return _detail(session, case)


@router.post("/cases/{case_id}/approve", response_model=ReviewCaseDetail)
def approve_case(
    case_id: int,
    req: DecisionRequest,
    reviewer: Principal = Depends(require_reviewer),
    session=Depends(get_db),
):
    return _decide(case_id, "APPROVED", req, reviewer, session)


@router.post("/cases/{case_id}/reject", response_model=ReviewCaseDetail)
def reject_case(
    case_id: int,
    req: DecisionRequest,
    reviewer: Principal = Depends(require_reviewer),
    session=Depends(get_db),
):
    return _decide(case_id, "REJECTED", req, reviewer, session)
