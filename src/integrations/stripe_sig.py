"""Stripe webhook signature verification over the raw request body.

Stripe signs ``{timestamp}.{raw_body}`` with HMAC-SHA256 using the webhook
signing secret. We compare all ``v1`` signatures with a constant-time compare
and reject stale timestamps (replay protection).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time


class WebhookVerificationError(Exception):
    pass


def verify_stripe_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> dict:
    if not secret:
        raise WebhookVerificationError("Webhook signing secret is not configured.")
    if not signature_header:
        raise WebhookVerificationError("Missing Stripe-Signature header.")

    timestamps: list[str] = []
    signatures: list[str] = []
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == "t":
            timestamps.append(value.strip())
        elif key.strip() == "v1":
            signatures.append(value.strip())

    if not timestamps or not signatures:
        raise WebhookVerificationError("Malformed Stripe-Signature header.")

    timestamp = timestamps[0]
    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError("Malformed Stripe-Signature timestamp.") from exc

    current = now if now is not None else int(time.time())
    if tolerance_seconds and abs(current - signed_at) > tolerance_seconds:
        raise WebhookVerificationError("Stripe-Signature timestamp is outside the tolerance.")

    signed_payload = timestamp.encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise WebhookVerificationError("Stripe-Signature verification failed.")

    try:
        return json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebhookVerificationError("Invalid JSON webhook payload.") from exc
