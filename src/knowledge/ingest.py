"""Policy ingestion CLI.

    python -m src.knowledge.ingest            # idempotent upsert
    python -m src.knowledge.ingest --reindex  # force re-embedding + chunk rebuild

Requires the policy tables (``alembic upgrade head``). Embeddings are configured
independently from DeepSeek chat (see ``src/knowledge/embeddings.py``).
"""

from __future__ import annotations

import argparse

from src.backend.db import configure_engine, get_session
from src.knowledge.embeddings import get_embedder
from src.knowledge.policies import ingest_policies


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest versioned store policies.")
    parser.add_argument("--reindex", action="store_true", help="force re-embedding")
    args = parser.parse_args()

    configure_engine()
    session = get_session()
    try:
        stats = ingest_policies(session, get_embedder(), force=args.reindex)
    finally:
        session.close()
    print(f"Ingested {stats['documents']} documents, {stats['chunks']} chunks.")


if __name__ == "__main__":
    main()
