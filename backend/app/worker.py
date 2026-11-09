"""Webhook worker: `python -m app.worker`.

Runs the inbox drain in a loop. Run as many copies as needed: claims use row locks
(SKIP LOCKED on PostgreSQL), so workers never process the same event twice.

Environment: DATABASE_URL, SECRET_KEY (as for the API), WORKER_POLL_SECONDS (default 2),
WORKER_BATCH_SIZE (default 50).
"""
import logging
import os
import time

from app.db.base import session_factory
from app.services.payments import drain

log = logging.getLogger("repaymaster.worker")


def run_forever(poll_seconds: float, batch_size: int, max_loops: int | None = None, factory=None) -> None:
    factory = factory or session_factory()
    loops = 0
    while True:
        summary = drain(factory, limit=batch_size)
        if summary["claimed"]:
            log.info("drained batch: %s", summary)
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return
        if not summary["claimed"]:
            time.sleep(poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_forever(poll_seconds=float(os.environ.get("WORKER_POLL_SECONDS", "2")),
                batch_size=int(os.environ.get("WORKER_BATCH_SIZE", "50")))


if __name__ == "__main__":
    main()
