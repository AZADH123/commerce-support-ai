"""OIDC authentication: validate Keycloak access tokens and expose public config.

The browser performs Authorization Code + PKCE against Keycloak and sends the
resulting access token to this API in an ``Authorization: Bearer`` header. This
module validates the token's issuer, audience, signature (RS256 via JWKS), and
expiry, then the identity is mapped to a local ``User`` by the stable ``sub``
claim.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient, PyJWKClientError

logger = logging.getLogger("support_agent.auth")

# Local defaults match the bundled Keycloak realm in keycloak/realm-export.json
# and docker-compose.yml.
DEFAULT_ISSUER = "http://localhost:8080/realms/support"
DEFAULT_AUDIENCE = "commerce-support-web"
DEFAULT_REVIEWER_ROLE = "reviewer"

# PyJWT >= 2.10 moved this error; keep a fallback for older versions.
try:
    from jwt import InvalidTokenError  # noqa: F401
except ImportError:  # pragma: no cover
    InvalidTokenError = jwt.PyJWTError  # type: ignore


class TokenValidationError(Exception):
    """Raised when an access token is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    audience: str
    client_id: str
    reviewer_role: str
    jwks_uri: str
    authorize_endpoint: str
    token_endpoint: str
    end_session_endpoint: str
    scope: str = "openid profile email"


def get_oidc_config() -> OidcConfig:
    issuer = (os.environ.get("OIDC_ISSUER") or DEFAULT_ISSUER).rstrip("/")
    audience = os.environ.get("OIDC_AUDIENCE") or DEFAULT_AUDIENCE
    client_id = os.environ.get("OIDC_CLIENT_ID") or audience
    reviewer_role = os.environ.get("OIDC_REVIEWER_ROLE") or DEFAULT_REVIEWER_ROLE
    jwks_uri = os.environ.get("OIDC_JWKS_URI") or f"{issuer}/protocol/openid-connect/certs"
    return OidcConfig(
        issuer=issuer,
        audience=audience,
        client_id=client_id,
        reviewer_role=reviewer_role,
        jwks_uri=jwks_uri,
        authorize_endpoint=f"{issuer}/protocol/openid-connect/auth",
        token_endpoint=f"{issuer}/protocol/openid-connect/token",
        end_session_endpoint=f"{issuer}/protocol/openid-connect/logout",
    )


_jwks_client: PyJWKClient | None = None


def get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(get_oidc_config().jwks_uri, cache_keys=True)
    return _jwks_client


def get_signing_key(token: str):
    """Resolve the RS256 public key for this token. Monkeypatched in tests."""
    return get_jwks_client().get_signing_key_from_jwt(token).key


def validate_token(token: str) -> dict:
    """Validate a bearer token and return its claims.

    Raises :class:`TokenValidationError` on any failure. Never leaks the token
    or provider error bodies into the exception message.
    """
    if not token:
        raise TokenValidationError("Missing access token.")
    config = get_oidc_config()
    try:
        key = get_signing_key(token)
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=config.audience,
            issuer=config.issuer,
            options={"require": ["sub", "exp", "iss"], "verify_exp": True, "verify_aud": True},
        )
    except InvalidTokenError as exc:
        # Include only the error class, never the token or raw provider body.
        raise TokenValidationError(f"Invalid access token ({type(exc).__name__}).") from None
    except PyJWKClientError as exc:
        raise TokenValidationError("Unable to fetch signing keys.") from None

    sub = claims.get("sub")
    if not sub:
        raise TokenValidationError("Token is missing the 'sub' claim.")
    return claims


def role_from_claims(claims: dict, config: OidcConfig) -> str:
    """Derive a local role from validated claims (never from request arguments)."""
    from src.backend.constants import ROLE_CUSTOMER, ROLE_REVIEWER

    realm_access = claims.get("realm_access") or {}
    roles = realm_access.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if config.reviewer_role in roles:
        return ROLE_REVIEWER
    # Also accept a top-level `roles` claim as a convenience for custom mappers.
    top_level = claims.get("roles") or []
    if isinstance(top_level, str):
        top_level = [top_level]
    if config.reviewer_role in top_level:
        return ROLE_REVIEWER
    return ROLE_CUSTOMER


def public_config() -> dict:
    """Public OIDC configuration for the browser (no secrets)."""
    c = get_oidc_config()
    return {
        "issuer": c.issuer,
        "client_id": c.client_id,
        "audience": c.audience,
        "scope": c.scope,
        "authorize_endpoint": c.authorize_endpoint,
        "token_endpoint": c.token_endpoint,
        "end_session_endpoint": c.end_session_endpoint,
    }
