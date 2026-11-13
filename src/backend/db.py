"""Database engine/session management.

Supports PostgreSQL (the production/local-Docker target, via ``DATABASE_URL``)
and keeps the original SQLite file as a fallback so existing local data is
preserved and tests can run in-memory.

URL resolution order:
    1. ``DATABASE_URL``   (e.g. postgresql+psycopg://support:support@localhost:5432/support)
    2. ``SUPPORT_AGENT_DB_URL``   (legacy name, kept for compatibility)
    3. local SQLite file ``support_agent_v2.db`` (new dev fallback; the legacy
       ``support_agent.db`` from the pre-migration checkout is left untouched)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from src.backend.models import Base

# Worker/dispatcher/seed processes import this module directly, so load local
# environment configuration here as well as in the API process.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "support_agent_v2.db"

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_default_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPPORT_AGENT_DB_URL")
    if url:
        return url
    return f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"


def get_engine(db_url: str | None = None) -> Engine:
    url = db_url or get_default_url()
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, echo=False, connect_args=connect_args)


def get_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    # Import models so their tables register on Base.metadata before create_all.
    from src.backend import models  # noqa: F401
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    # PostgreSQL needs the pgvector extension before a vector column can exist.
    if engine.dialect.name == "postgresql":
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except DBAPIError as exc:
            raise RuntimeError(
                "The pgvector extension is not available in the configured PostgreSQL. "
                "Use the pgvector/pgvector:pg16 image (docker compose) or install the "
                "'vector' extension, then recreate the database."
            ) from exc

    Base.metadata.create_all(engine)


def configure_engine(db_url: str | None = None) -> Engine:
    """Bind the process-wide default engine (used by tests and standalone runs)."""
    global _engine, _SessionLocal
    engine = get_engine(db_url)
    init_db(engine)
    _SessionLocal = get_session_factory(engine)
    _engine = engine
    return engine


def bind_engine(engine: Engine) -> Engine:
    """Bind an already-constructed engine (e.g. a StaticPool in-memory SQLite in tests)."""
    global _engine, _SessionLocal
    init_db(engine)
    _SessionLocal = get_session_factory(engine)
    _engine = engine
    return engine


def ensure_engine() -> tuple[Engine, sessionmaker]:
    global _engine, _SessionLocal
    if _engine is None or _SessionLocal is None:
        configure_engine()
    return _engine, _SessionLocal


def get_session():
    """Open a session from the process-wide default engine."""
    _, factory = ensure_engine()
    return factory()
