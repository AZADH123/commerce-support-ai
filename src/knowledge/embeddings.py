"""Embedding providers.

Embeddings are configured independently from the DeepSeek chat model:

- ``hashing`` (default) — deterministic, offline, 384-d. Used by tests and the
  local demo so retrieval is reproducible without network access.
- ``openai`` — any OpenAI-compatible ``/embeddings`` endpoint
  (``EMBEDDING_BASE_URL``, ``EMBEDDING_API_KEY``, ``EMBEDDING_MODEL``).
  ``text-embedding-3-small`` is 1536-d; set ``EMBEDDING_DIM`` to match.

The vector dimension must match the ``PortableVector``/pgvector column and the
reindex procedure documented in the README.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

import httpx

DEFAULT_EMBEDDING_DIM = 384


class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic bag-of-tokens hashing embedder (no external calls)."""

    def __init__(self, dim: int = DEFAULT_EMBEDDING_DIM):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dim
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[index] += sign
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors


class OpenAICompatibleEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, dim: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        vectors = [item["embedding"] for item in data]
        if any(len(v) != self.dim for v in vectors):
            raise ValueError("Embedding dimension does not match EMBEDDING_DIM.")
        return vectors


def get_embedder() -> Embedder:
    provider = (os.environ.get("EMBEDDING_PROVIDER") or "hashing").strip().lower()
    if provider == "openai":
        dim = int(os.environ.get("EMBEDDING_DIM", "1536"))
        return OpenAICompatibleEmbedder(
            base_url=os.environ.get("EMBEDDING_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ.get("EMBEDDING_API_KEY", ""),
            model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
            dim=dim,
        )
    return HashingEmbedder(int(os.environ.get("EMBEDDING_DIM", str(DEFAULT_EMBEDDING_DIM))))
