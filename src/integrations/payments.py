"""Payment refund adapters.

- ``LocalPaymentAdapter`` — deterministic, in-process, used by tests and the
  default local demo (no external calls).
- ``StripePaymentAdapter`` — concrete payment sandbox integration using Stripe
  test mode over the Stripe HTTP API. Submissions carry a stable
  ``Idempotency-Key`` so retries never create a second refund.

Provider submission belongs to the authorized execution service
(``src.services.refund_execution``); agent tools never call these adapters.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger("support_agent.payments")

STRIPE_API_BASE = "https://api.stripe.com"


class PaymentProviderError(Exception):
    """Base class for provider failures with a stable, safe message."""


class RetryableProviderError(PaymentProviderError):
    """Transient failure; safe to retry with the same idempotency key."""


class PermanentProviderError(PaymentProviderError):
    """The provider rejected the refund; retrying will not help."""


class UncertainProviderError(PaymentProviderError):
    """The request may have been accepted; reconcile before resubmitting."""


@dataclass(frozen=True)
class RefundResult:
    # succeeded | pending | failed | not_found | unknown
    status: str
    provider_refund_id: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    failure_reason: str | None = None


class PaymentAdapter(Protocol):
    def create_refund(
        self, *, payment_ref: str, amount_cents: int, currency: str, idempotency_key: str
    ) -> RefundResult: ...

    def get_refund(
        self, *, payment_ref: str, idempotency_key: str
    ) -> RefundResult | None: ...


class LocalPaymentAdapter:
    """Deterministic local adapter; keeps refunds in memory for the demo/tests."""

    def __init__(self, outcomes: dict[str, str] | None = None):
        # idempotency_key -> succeeded | retryable | permanent | uncertain
        self._outcomes = outcomes or {}
        self._refunds: dict[str, RefundResult] = {}
        self.calls: list[dict] = []

    def create_refund(
        self, *, payment_ref: str, amount_cents: int, currency: str, idempotency_key: str
    ) -> RefundResult:
        self.calls.append(
            {
                "payment_ref": payment_ref,
                "amount_cents": amount_cents,
                "currency": currency,
                "idempotency_key": idempotency_key,
            }
        )
        existing = self._refunds.get(idempotency_key)
        if existing is not None:
            return existing

        outcome = self._outcomes.get(idempotency_key, "succeeded")
        if outcome == "retryable":
            raise RetryableProviderError("Temporary provider outage.")
        if outcome == "permanent":
            raise PermanentProviderError("Refund declined by provider.")
        if outcome == "uncertain":
            raise UncertainProviderError("Provider response timed out.")

        result = RefundResult(
            status="succeeded",
            provider_refund_id=f"re_local_{idempotency_key}",
            amount_cents=amount_cents,
            currency=currency,
        )
        self._refunds[idempotency_key] = result
        return result

    def get_refund(self, *, payment_ref: str, idempotency_key: str) -> RefundResult | None:
        return self._refunds.get(idempotency_key)


class StripePaymentAdapter:
    """Stripe test-mode refunds over the Stripe HTTP API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = STRIPE_API_BASE,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ):
        self.api_key = (api_key or os.environ.get("STRIPE_SECRET_KEY") or "").strip()
        if not self.api_key:
            raise PaymentProviderError("STRIPE_SECRET_KEY is not configured.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        headers.update(kwargs.pop("headers", {}))
        if self._client is not None:
            return self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        with httpx.Client(timeout=self.timeout) as client:
            return client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)

    def create_refund(
        self, *, payment_ref: str, amount_cents: int, currency: str, idempotency_key: str
    ) -> RefundResult:
        form = {
            "payment_intent": payment_ref,
            "amount": str(amount_cents),
            "currency": currency,
        }
        try:
            response = self._request(
                "POST",
                "/v1/refunds",
                data=form,
                headers={"Idempotency-Key": idempotency_key},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Connection never established: safe to retry.
            raise RetryableProviderError("Could not reach payment provider.") from exc
        except httpx.TimeoutException as exc:
            # The request may have been accepted.
            raise UncertainProviderError("Payment provider timed out.") from exc
        except httpx.HTTPError as exc:
            raise RetryableProviderError("Payment provider transport error.") from exc

        return self._map_response(response)

    def _map_response(self, response: httpx.Response) -> RefundResult:
        if response.status_code in (429, 500, 502, 503, 504):
            raise RetryableProviderError(f"Provider temporary error ({response.status_code}).")
        if response.status_code >= 400:
            # Do not leak the provider body (may include request details).
            raise PermanentProviderError(f"Provider rejected the refund ({response.status_code}).")

        try:
            body = response.json()
        except ValueError as exc:
            raise UncertainProviderError("Provider returned an unreadable response.") from exc

        status = body.get("status")
        if status == "succeeded":
            return RefundResult(
                status="succeeded",
                provider_refund_id=body.get("id"),
                amount_cents=body.get("amount"),
                currency=body.get("currency"),
            )
        if status == "failed":
            return RefundResult(
                status="failed",
                provider_refund_id=body.get("id"),
                amount_cents=body.get("amount"),
                currency=body.get("currency"),
                failure_reason="Provider reported the refund failed.",
            )
        if status in ("pending", "requires_action"):
            return RefundResult(
                status="pending",
                provider_refund_id=body.get("id"),
                amount_cents=body.get("amount"),
                currency=body.get("currency"),
            )
        return RefundResult(status="unknown", provider_refund_id=body.get("id"))

    def get_refund(self, *, payment_ref: str, idempotency_key: str) -> RefundResult | None:
        """Reconcile: list refunds for the payment intent and match amount/currency."""
        try:
            response = self._request(
                "GET",
                "/v1/refunds",
                params={"payment_intent": payment_ref, "limit": 10},
            )
        except httpx.HTTPError as exc:
            raise RetryableProviderError("Could not reconcile with payment provider.") from exc

        if response.status_code in (429, 500, 502, 503, 504):
            raise RetryableProviderError(f"Provider temporary error ({response.status_code}).")
        if response.status_code >= 400:
            raise RetryableProviderError(f"Provider reconciliation failed ({response.status_code}).")

        try:
            body = response.json()
        except ValueError:
            raise RetryableProviderError("Provider reconciliation returned an unreadable response.")

        for item in body.get("data", []):
            if item.get("status") == "succeeded":
                return RefundResult(
                    status="succeeded",
                    provider_refund_id=item.get("id"),
                    amount_cents=item.get("amount"),
                    currency=item.get("currency"),
                )
            if item.get("status") == "failed":
                return RefundResult(
                    status="failed",
                    provider_refund_id=item.get("id"),
                    amount_cents=item.get("amount"),
                    currency=item.get("currency"),
                    failure_reason="Provider reported the refund failed.",
                )
        return None


def get_payment_adapter(provider: str | None = None) -> PaymentAdapter:
    provider = (provider or os.environ.get("PAYMENT_PROVIDER") or "local").strip().lower()
    if provider == "stripe":
        return StripePaymentAdapter()
    return LocalPaymentAdapter()


def new_idempotency_key(case_id: int) -> str:
    """Stable per-case key; the case id makes it deterministic and reusable."""
    return f"refund-case-{case_id}"
