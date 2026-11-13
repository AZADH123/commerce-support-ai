"""Commerce adapter: trusted order/ownership/shipping lookup.

The refund execution service never trusts model-generated amounts or payment
references. It obtains ownership, payment reference, amount, and currency from
the backend through this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select

from src.backend import constants as C
from src.backend.models import Order, Payment

_SHIPPING_MESSAGES = {
    C.ORDER_PLACED: "Order placed, not yet shipped.",
    C.ORDER_SHIPPED: "In transit.",
    C.ORDER_DELIVERED: "Delivered.",
    C.ORDER_CANCELLED: "Order was cancelled; no shipment in progress.",
}


@dataclass(frozen=True)
class OrderSnapshot:
    order_id: int
    customer_id: int
    status: str
    amount: float
    payment_id: int | None
    payment_status: str | None
    payment_amount: float | None
    provider: str | None
    provider_payment_id: str | None
    currency: str
    shipping_message: str


class CommerceAdapter(Protocol):
    def get_order(self, order_id: int) -> OrderSnapshot | None: ...


class LocalCommerceAdapter:
    """Deterministic adapter backed by the application's own database."""

    def __init__(self, session):
        self.session = session

    def get_order(self, order_id: int) -> OrderSnapshot | None:
        order = self.session.get(Order, order_id)
        if order is None:
            return None
        payment = self.session.execute(
            select(Payment).where(Payment.order_id == order.order_id)
        ).scalar_one_or_none()
        return OrderSnapshot(
            order_id=order.order_id,
            customer_id=order.customer_id,
            status=order.status,
            amount=order.amount,
            payment_id=payment.payment_id if payment else None,
            payment_status=payment.status if payment else None,
            payment_amount=payment.amount if payment else None,
            provider=payment.provider if payment else None,
            provider_payment_id=payment.provider_payment_id if payment else None,
            currency=payment.currency if payment else "usd",
            shipping_message=_SHIPPING_MESSAGES.get(order.status, "Unknown status."),
        )
