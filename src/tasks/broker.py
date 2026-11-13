"""Taskiq broker: Redis in production/local Docker, in-memory fallback otherwise."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from taskiq import InMemoryBroker

load_dotenv()


def build_broker():
    url = os.environ.get("REDIS_URL")
    if url:
        try:
            from taskiq_redis import ListQueueBroker

            return ListQueueBroker(url)
        except Exception:  # noqa: BLE001 - fall back to in-memory
            pass
    return InMemoryBroker()


broker = build_broker()
