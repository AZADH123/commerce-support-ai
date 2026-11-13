"""Repeatable seed data: two customers, one reviewer, and owned orders.

The customer ``sub`` values match the user ids imported into the local Keycloak
realm (``keycloak/realm-export.json``), so a Keycloak login maps to the same
stable identity the seed data is attached to. Seeding is idempotent: it upserts
by natural keys and never deletes existing rows (so existing local data is
preserved).

Demo identities:
    alice    — customer  (orders 1001, 1002, 1003)
    bob      — customer  (orders 1004, 1005, 1006)
    reviewer — reviewer  (realm role ``reviewer``)

Run:  python -m src.backend.seed
"""

from __future__ import annotations

from datetime import date

from src.backend.constants import (
    ORDER_CANCELLED,
    ORDER_DELIVERED,
    ORDER_PLACED,
    ORDER_SHIPPED,
    ROLE_CUSTOMER,
    ROLE_REVIEWER,
)
from src.backend.db import configure_engine, get_session
from src.backend.models import Order, Payment, User
from src.services.users import get_or_create_user

DEMO_USERS = [
    {
        "key": "alice",
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "alice@example.com",
        "name": "Alice Chen",
        "role": ROLE_CUSTOMER,
    },
    {
        "key": "bob",
        "sub": "22222222-2222-2222-2222-222222222222",
        "email": "bob@example.com",
        "name": "Ben Torres",
        "role": ROLE_CUSTOMER,
    },
    {
        "key": "reviewer",
        "sub": "33333333-3333-3333-3333-333333333333",
        "email": "reviewer@example.com",
        "name": "Rita Reviewer",
        "role": ROLE_REVIEWER,
    },
]

DEMO_SUBS = {user["key"]: user["sub"] for user in DEMO_USERS}

# Orders grouped by owner key: (order_id, item, status, order_date, amount).
DEMO_ORDERS = {
    "alice": [
        (1001, "Wireless Headphones", ORDER_DELIVERED, date(2026, 6, 1), 79.99),
        (1002, "Mechanical Keyboard", ORDER_SHIPPED, date(2026, 6, 20), 129.00),
        (1003, "USB-C Hub", ORDER_PLACED, date(2026, 6, 28), 34.50),
    ],
    "bob": [
        (1004, "Standing Desk", ORDER_DELIVERED, date(2026, 5, 15), 349.00),
        (1005, "Desk Lamp", ORDER_CANCELLED, date(2026, 6, 10), 24.99),
        (1006, "Bluetooth Speaker", ORDER_DELIVERED, date(2026, 6, 5), 59.99),
    ],
}

# Payments keyed by order_id: (payment_id, status, method, amount).
DEMO_PAYMENTS = {
    1001: (1, "paid", "card", 79.99),
    1002: (2, "paid", "card", 129.00),
    1003: (3, "pending", "card", 34.50),
    1004: (4, "paid", "paypal", 349.00),
    1005: (5, "refunded", "card", 24.99),
    1006: (6, "paid", "card", 59.99),
}


def _upsert_users(session) -> dict[str, User]:
    users: dict[str, User] = {}
    for spec in DEMO_USERS:
        users[spec["key"]] = get_or_create_user(
            session,
            sub=spec["sub"],
            email=spec["email"],
            name=spec["name"],
            role=spec["role"],
        )
    return users


def seed(session) -> None:
    users = _upsert_users(session)

    for owner_key, orders in DEMO_ORDERS.items():
        customer_id = users[owner_key].id
        for order_id, item, status, order_date, amount in orders:
            session.merge(
                Order(
                    order_id=order_id,
                    customer_id=customer_id,
                    item=item,
                    status=status,
                    order_date=order_date,
                    amount=amount,
                )
            )

    for order_id, (payment_id, status, method, amount) in DEMO_PAYMENTS.items():
        session.merge(
            Payment(
                payment_id=payment_id,
                order_id=order_id,
                status=status,
                method=method,
                amount=amount,
                provider="local",
                provider_payment_id=f"local_pay_{payment_id}",
                currency="usd",
            )
        )

    session.commit()


if __name__ == "__main__":
    configure_engine()
    session = get_session()
    seed(session)
    n_users = len(DEMO_USERS)
    n_orders = sum(len(orders) for orders in DEMO_ORDERS.values())
    n_payments = len(DEMO_PAYMENTS)
    print(f"Seeded {n_users} users, {n_orders} orders, {n_payments} payments.")
