"""Provider webhook receivers (signature-verified, no OIDC)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.deps import get_db
from src.integrations.stripe_sig import WebhookVerificationError, verify_stripe_signature
from src.services.webhooks import process_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, session=Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = verify_stripe_signature(raw_body, signature, secret)
    except WebhookVerificationError as exc:
        # 400 tells Stripe to retry; never echo the payload or secret.
        raise HTTPException(status_code=400, detail=str(exc)) from None

    record = process_event(session, provider="stripe", event=event)
    return {"received": True, "status": record.status}
