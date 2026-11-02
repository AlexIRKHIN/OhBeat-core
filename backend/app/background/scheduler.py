"""Scheduler: periodic system jobs (System_Architecture.md §3).

Now: FR-8 — beats stuck in `uploading` for more than 24 hours become `deleted`.
Slice 3 adds FR-29 (expired reservations and unpaid orders).

Every job is a single idempotent UPDATE, so running two schedulers at once is harmless.

Run:  python -m app.background.scheduler
"""

import logging
import time

from app.catalog.service import delete_abandoned_uploads
from app.common.db import get_session_factory

log = logging.getLogger("scheduler")

INTERVAL_SECONDS = 60  # "once a minute"

JOBS = [
    ("FR-8 abandoned uploads", delete_abandoned_uploads),
]


def run_once() -> None:
    session_factory = get_session_factory()
    for name, job in JOBS:
        try:
            with session_factory() as db:
                changed = job(db)
            if changed:
                log.info("%s: %s row(s) changed", name, changed)
        except Exception:
            log.exception("%s failed", name)


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log.info("scheduler started, interval %s s", INTERVAL_SECONDS)
    while True:
        started = time.monotonic()
        run_once()
        time.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    run_forever()
