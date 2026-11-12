"""Notifications to users (FR-5, FR-12) and SMS codes of the signature (RFC ПЭП).
Provider of SMS and email is outside the system, so it lives behind an interface;
locally a mock writes every message to the log.

ASSUMPTION: GAP-55 — email to users.email, in Russian, sent right after the status change is committed.
"""

import logging
from functools import lru_cache
from typing import Protocol

from app.common.config import get_settings

log = logging.getLogger("notifications")


class SmsUnavailable(Exception):
    """The SMS provider did not take the message (GAP-72)."""


class Notifier(Protocol):
    def send_email(self, to: str, subject: str, body: str) -> None: ...

    def send_sms(self, phone: str, text: str) -> None: ...


class LogNotifier:
    """Mock provider: the "sent" email is a log line. See it with  docker compose logs media-results"""

    def send_email(self, to: str, subject: str, body: str) -> None:
        log.info("EMAIL to=%s | %s | %s", to, subject, body.replace("\n", " / "))

    def send_sms(self, phone: str, text: str) -> None:
        """The "delivered" SMS is a log line too:  docker compose logs api | grep SMS
        The code is in the log on purpose: locally that is how it reaches the buyer (CLAUDE.md)."""
        if get_settings().sms_mode == "unavailable":
            raise SmsUnavailable("SMS_MODE=unavailable")
        log.info("SMS to=%s | %s", phone, text)


@lru_cache
def get_notifier() -> Notifier:
    return LogNotifier()
