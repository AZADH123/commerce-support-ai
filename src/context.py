"""Request/execution context via :mod:`contextvars`.

Two pieces of ambient state are threaded through the agent/tool/service layer
without changing tool signatures (which the LLM drives):

- ``Principal``: the authenticated identity resolved from the validated request,
  so business rules (ownership, reviewer permissions) never trust model-generated
  arguments.
- ``session``: the request-scoped SQLAlchemy session, so a case transition and
  its audit event are committed atomically in the same transaction.

Both default safely when unset (standalone tool use, tests, seeding).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    user_id: int
    role: str
    sub: str
    email: str | None = None
    name: str = ""


_principal_cv: ContextVar[Principal | None] = ContextVar("principal", default=None)
_session_cv: ContextVar = ContextVar("db_session", default=None)


def set_principal(principal: Principal | None):
    return _principal_cv.set(principal)


def get_principal() -> Principal | None:
    return _principal_cv.get()


def reset_principal(token) -> None:
    _principal_cv.reset(token)


def set_session(session):
    return _session_cv.set(session)


def reset_session(token) -> None:
    _session_cv.reset(token)


def get_session():
    """Return the request-scoped session if bound, otherwise a default session."""
    session = _session_cv.get()
    if session is not None:
        return session
    from src.backend.db import get_session as default_session

    return default_session()
