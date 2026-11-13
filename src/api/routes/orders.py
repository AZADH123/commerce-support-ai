"""Customer orders endpoint (read-only, owner-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from src.api.deps import get_current_user, get_db
from src.api.schemas import OrderOut
from src.backend.models import Order
from src.context import Principal

router = APIRouter(prefix="/api", tags=["orders"])


@router.get("/orders", response_model=list[OrderOut])
def list_orders(principal: Principal = Depends(get_current_user), session=Depends(get_db)):
    orders = session.execute(
        select(Order).where(Order.customer_id == principal.user_id).order_by(Order.order_id)
    ).scalars()
    return [
        OrderOut(
            order_id=order.order_id,
            item=order.item,
            status=order.status,
            order_date=order.order_date.isoformat(),
            amount=order.amount,
        )
        for order in orders
    ]
