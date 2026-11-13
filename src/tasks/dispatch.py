"""Dispatcher CLI: ``python -m src.tasks.dispatch [--loop] [--interval N]``."""

from __future__ import annotations

import argparse
import time

from src.backend import db
from src.outbox.dispatcher import dispatch_pending, recover_stale


def run_once() -> dict:
    session = db.get_session()
    try:
        result = dispatch_pending(session)
        result["recovered"] = recover_stale(session)
        return result
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch pending outbox records.")
    parser.add_argument("--loop", action="store_true", help="keep running")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between passes")
    args = parser.parse_args()

    while True:
        result = run_once()
        print(f"dispatched={result['sent']} failed={result['failed']} recovered={result['recovered']}")
        if not args.loop:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
