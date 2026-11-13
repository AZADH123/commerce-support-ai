"""Alembic environment: bind to the same database the app uses."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Make the project root importable so ``src`` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backend.db import get_default_url  # noqa: E402
from src.backend.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    env_url = os.environ.get("DATABASE_URL") or os.environ.get("SUPPORT_AGENT_DB_URL")
    if env_url:
        return env_url
    return config.get_main_option("sqlalchemy.url") or get_default_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
