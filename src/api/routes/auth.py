"""Public OIDC config and the authenticated identity endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.auth import public_config
from src.api.deps import get_current_user
from src.api.schemas import MeResponse
from src.context import Principal

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/auth/config")
def auth_config():
    """Public OIDC configuration for the browser PKCE flow (no secrets)."""
    return public_config()


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(get_current_user)):
    return MeResponse(
        id=principal.user_id,
        sub=principal.sub,
        email=principal.email,
        name=principal.name,
        role=principal.role,
    )
