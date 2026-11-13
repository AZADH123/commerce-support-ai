"""Shared fixtures: in-memory SQLite + seeded demo data + authenticated client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

import api
from src.api.deps import get_current_user
from src.backend import db
from src.backend.models import User
from src.backend.seed import DEMO_SUBS, seed
from src.context import Principal


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.bind_engine(engine)
    yield engine
    db._engine = None
    db._SessionLocal = None
    engine.dispose()


@pytest.fixture
def session(engine):
    s = db.get_session()
    yield s
    s.close()


@pytest.fixture
def seeded(engine):
    s = db.get_session()
    seed(s)
    s.close()
    return engine


def make_principal(session, key: str) -> Principal:
    sub = DEMO_SUBS[key]
    user = session.execute(select(User).where(User.sub == sub)).scalar_one()
    return Principal(user_id=user.id, role=user.role, sub=sub, email=user.email, name=user.name)


@pytest.fixture
def client(seeded):
    """TestClient whose auth dependency returns a settable principal."""
    holder: dict = {}

    def override():
        principal = holder.get("principal")
        if principal is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated.")
        return principal

    app = api.app
    app.dependency_overrides[get_current_user] = override
    with TestClient(app) as c:
        c._holder = holder  # type: ignore[attr-defined]

        def set_principal(key: str):
            s = db.get_session()
            try:
                holder["principal"] = make_principal(s, key)
            finally:
                s.close()

        c.set_principal = set_principal  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def case_factory(seeded):
    """Create a refund case for a demo customer through the service layer."""

    def _create(key: str, order_id: int, reason: str = "Item broken"):
        from src.services import cases as cases_service

        s = db.get_session()
        try:
            user = s.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one()
            return cases_service.request_refund(
                s, customer_id=user.id, order_id=order_id, reason=reason
            )
        finally:
            s.close()

    return _create
