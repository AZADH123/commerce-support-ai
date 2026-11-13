"""FastAPI dependencies: database session and authenticated identity."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from src.api.auth import TokenValidationError, get_oidc_config, role_from_claims, validate_token
from src.backend.constants import ROLE_REVIEWER
from src.backend.db import get_session as default_session
from src.context import Principal
from src.services.users import get_or_create_user


def get_db():
    """Yield a request-scoped session; commit on success, rollback on error."""
    session = default_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(request: Request, session=Depends(get_db)) -> Principal:
    """Resolve the authenticated identity from the bearer token's validated claims.

    Identity is mapped to a local ``User`` by the stable ``sub`` claim; the role
    comes from validated claims, never from request arguments.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    token = auth_header[len("Bearer "):].strip()
    try:
        claims = validate_token(token)
    except TokenValidationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None

    config = get_oidc_config()
    role = role_from_claims(claims, config)
    sub = claims["sub"]
    email = claims.get("email")
    name = claims.get("preferred_username") or claims.get("name") or email or ""
    user = get_or_create_user(session, sub=sub, email=email, name=name, role=role)
    return Principal(user_id=user.id, role=user.role, sub=sub, email=email, name=name)


def require_reviewer(principal: Principal = Depends(get_current_user)) -> Principal:
    if principal.role != ROLE_REVIEWER:
        raise HTTPException(status_code=403, detail="Reviewer access required.")
    return principal
