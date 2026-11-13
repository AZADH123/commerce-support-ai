"""A portable vector column type.

On PostgreSQL this maps to a real ``pgvector`` ``vector(dim)`` column so the
Phase 2 migrations can add an ANN index. On SQLite (tests / dev fallback) it
stores the same list of floats as JSON, and retrieval falls back to an
in-process cosine scan. Dimension is fixed per store and documented in the
README (default: 384, hashing embedder).
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator


class PortableVector(TypeDecorator):
    impl = JSON
    cache_ok = False

    def __init__(self, dim: int = 384):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            import json

            value = json.loads(value)
        return [float(x) for x in value]
