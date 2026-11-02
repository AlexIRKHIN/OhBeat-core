"""Notifications to users (FR-5, FR-12). Provider of SMS and email is outside the system,
so it lives behind an interface; locally a mock writes every message to the log.

ASSUMPTION: GAP-55 — email to users.email, in Russian, sent right after the status change is committed.
"""

import logging
from functools import lru_cache
from typing import Protocol

log = logging.getLogger("notifications")


class Notifier(Protocol):
    def send_email(self, to: str, subject: str, body: str) -> None: ...


class LogNotifier:
    """Mock provider: the "sent" email is a log line. See it with  docker compose logs media-results"""

    def send_email(self, to: str, subject: str, body: str) -> None:
        log.info("EMAIL to=%s | %s | %s", to, subject, body.replace("\n", " / "))


@lru_cache
def get_notifier() -> Notifier:
    return LogNotifier()
