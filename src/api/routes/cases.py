"""Customer case list/detail endpoints (owner-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_current_user, get_db
from src.api.schemas import CaseDetail, CaseOut
from src.api.serializers import to_case_detail, to_case_out
from src.context import Principal
from src.services import cases as cases_service

router = APIRouter(prefix="/api", tags=["cases"])


@router.get("/cases", response_model=list[CaseOut])
def list_cases(
    status: str | None = Query(None),
    principal: Principal = Depends(get_current_user),
    session=Depends(get_db),
):
    cases = cases_service.list_cases_for_customer(
        session, customer_id=principal.user_id, status=status
    )
    return [to_case_out(case) for case in cases]


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: int,
    principal: Principal = Depends(get_current_user),
    session=Depends(get_db),
):
    case = cases_service.get_case_for_customer(
        session, case_id=case_id, customer_id=principal.user_id
    )
    return to_case_detail(case)
