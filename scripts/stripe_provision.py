"""Provision a Stripe *test-mode* payment intentionally for the live demo.

Usage (PowerShell, from repo root):

    $env:STRIPE_SECRET_KEY = "sk_test_..."
    .\.venv\Scripts\python.exe scripts\stripe_provision.py --order 1001

Creates a confirmed test PaymentIntent and points the order's seeded Payment row
at it (provider=stripe). Repeatable: re-running creates a new PaymentIntent and
re-points the row. Never use a live key with synthetic orders.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from src.backend.db import configure_engine, get_session
from src.backend.models import Payment

STRIPE_API_BASE = "https://api.stripe.com"


def _create_test_payment_intent(secret_key: str, amount_cents: int, currency: str) -> str:
    response = httpx.post(
        f"{STRIPE_API_BASE}/v1/payment_intents",
        headers={"Authorization": f"Bearer {secret_key}"},
        data={
            "amount": str(amount_cents),
            "currency": currency,
            "payment_method": "pm_card_visa",
            "confirm": "true",
            "automatic_payment_methods[enabled]": "true",
            "description": "Synthetic commerce-support demo order",
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        raise SystemExit(f"Stripe error {response.status_code}: could not create PaymentIntent.")
    body = response.json()
    if body.get("status") != "succeeded":
        raise SystemExit(f"Unexpected PaymentIntent status: {body.get('status')}")
    return body["id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", type=int, default=1001)
    args = parser.parse_args()

    secret_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        raise SystemExit("Set STRIPE_SECRET_KEY (a sk_test_... key) first.")
    if secret_key.startswith("sk_live_"):
        raise SystemExit("Refusing to use a live Stripe key for synthetic demo orders.")

    configure_engine()
    session = get_session()
    try:
        payment = session.query(Payment).filter(Payment.order_id == args.order).one_or_none()
        if payment is None:
            raise SystemExit(f"No payment row for order {args.order}.")
        payment_intent = _create_test_payment_intent(
            secret_key, round(payment.amount * 100), payment.currency or "usd"
        )
        payment.provider = "stripe"
        payment.provider_payment_id = payment_intent
        session.commit()
        print(f"Order {args.order} payment now uses Stripe test PaymentIntent {payment_intent}.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
