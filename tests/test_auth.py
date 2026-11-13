import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import api
from src.api import auth
from src.api.auth import OidcConfig, TokenValidationError

ISSUER = "http://localhost:8080/realms/support"
AUDIENCE = "commerce-support-web"


@pytest.fixture
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


@pytest.fixture
def config(monkeypatch):
    cfg = OidcConfig(
        issuer=ISSUER,
        audience=AUDIENCE,
        client_id=AUDIENCE,
        reviewer_role="reviewer",
        jwks_uri=f"{ISSUER}/protocol/openid-connect/certs",
        authorize_endpoint=f"{ISSUER}/protocol/openid-connect/auth",
        token_endpoint=f"{ISSUER}/protocol/openid-connect/token",
        end_session_endpoint=f"{ISSUER}/protocol/openid-connect/logout",
    )
    monkeypatch.setattr(auth, "get_oidc_config", lambda: cfg)
    return cfg


def _sign(private_pem, *, sub="user-123", iss=ISSUER, aud=AUDIENCE, exp=None, extra=None):
    payload = {"sub": sub, "iss": iss, "aud": aud, "exp": exp or int(time.time()) + 300}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, private_pem, algorithm="RS256")


def _use_signing_key(monkeypatch, public_pem):
    monkeypatch.setattr(auth, "get_signing_key", lambda token: public_pem)


def test_validate_token_accepts_valid_token(keypair, config, monkeypatch):
    private_pem, public_pem = keypair
    _use_signing_key(monkeypatch, public_pem)
    token = _sign(private_pem, extra={"email": "alice@example.com"})
    claims = auth.validate_token(token)
    assert claims["sub"] == "user-123"


def test_validate_token_rejects_wrong_audience(keypair, config, monkeypatch):
    private_pem, public_pem = keypair
    _use_signing_key(monkeypatch, public_pem)
    token = _sign(private_pem, aud="some-other-client")
    with pytest.raises(TokenValidationError):
        auth.validate_token(token)


def test_validate_token_rejects_wrong_issuer(keypair, config, monkeypatch):
    private_pem, public_pem = keypair
    _use_signing_key(monkeypatch, public_pem)
    token = _sign(private_pem, iss="https://evil.example/realms/support")
    with pytest.raises(TokenValidationError):
        auth.validate_token(token)


def test_validate_token_rejects_expired(keypair, config, monkeypatch):
    private_pem, public_pem = keypair
    _use_signing_key(monkeypatch, public_pem)
    token = _sign(private_pem, exp=int(time.time()) - 10)
    with pytest.raises(TokenValidationError):
        auth.validate_token(token)


def test_validate_token_rejects_bad_signature(keypair, config, monkeypatch):
    private_pem, _public_pem = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_public = other.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    monkeypatch.setattr(auth, "get_signing_key", lambda token: other_public)
    token = _sign(private_pem)
    with pytest.raises(TokenValidationError):
        auth.validate_token(token)


def test_validate_token_rejects_missing_sub(keypair, config, monkeypatch):
    private_pem, public_pem = keypair
    _use_signing_key(monkeypatch, public_pem)
    token = _sign(private_pem, sub="")
    with pytest.raises(TokenValidationError):
        auth.validate_token(token)


def test_validate_token_rejects_empty():
    with pytest.raises(TokenValidationError):
        auth.validate_token("")


def test_role_from_claims():
    cfg = auth.get_oidc_config()
    assert auth.role_from_claims({"realm_access": {"roles": ["reviewer"]}}, cfg) == "reviewer"
    assert auth.role_from_claims({"realm_access": {"roles": []}}, cfg) == "customer"
    assert auth.role_from_claims({}, cfg) == "customer"


def test_expired_token_rejected_at_api_endpoint(engine, keypair, config, monkeypatch):
    """Integration: an expired bearer token fails through the real /api/me dependency."""
    private_pem, public_pem = keypair
    monkeypatch.setattr(auth, "get_signing_key", lambda token: public_pem)
    token = _sign(private_pem, exp=int(time.time()) - 10)
    with TestClient(api.app) as client:
        response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert token not in response.text
