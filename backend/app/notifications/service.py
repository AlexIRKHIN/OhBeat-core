"""Notifications to users (FR-5, FR-12) and SMS codes of the signature (RFC ПЭП).
Provider of SMS and email is outside the system, so it lives behind an interface;
locally a mock writes every message to the log.

Besides the log, the mock can put messages into an "inbox" file (MOCK_INBOX_PATH, one JSON per line):
the end-to-end test reads the SMS code from there, the way a person reads it on the phone.

ASSUMPTION: GAP-55 — email to users.email, in Russian, sent right after the status change is committed.
"""

import json
import logging
import os
import threading
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

from app.common.config import get_settings

log = logging.getLogger("notifications")
_inbox_lock = threading.Lock()


class SmsUnavailable(Exception):
    """The SMS provider did not take the message (GAP-72)."""


class Notifier(Protocol):
    def send_email(self, to: str, subject: str, body: str) -> None: ...

    def send_sms(self, phone: str, text: str) -> None: ...


def _to_inbox(message: dict) -> None:
    path = os.environ.get("MOCK_INBOX_PATH")
    if not path:
        return
    line = json.dumps({"at": datetime.now(UTC).isoformat(), **message}, ensure_ascii=False)
    try:
        with _inbox_lock, open(path, "a", encoding="utf-8") as inbox:
            inbox.write(line + "\n")
    except OSError as error:  # the inbox is a convenience; the message is in the log anyway
        log.warning("mock inbox %s is not writable: %s", path, error)


class LogNotifier:
    """Mock provider: the "sent" email is a log line. See it with  docker compose logs media-results"""

    def send_email(self, to: str, subject: str, body: str) -> None:
        log.info("EMAIL to=%s | %s | %s", to, subject, body.replace("\n", " / "))
        _to_inbox({"kind": "email", "to": to, "subject": subject, "text": body})

    def send_sms(self, phone: str, text: str) -> None:
        """The "delivered" SMS is a log line too:  docker compose logs api | grep SMS
        The code is in the log on purpose: locally that is how it reaches the buyer (CLAUDE.md)."""
        if get_settings().sms_mode == "unavailable":
            raise SmsUnavailable("SMS_MODE=unavailable")
        log.info("SMS to=%s | %s", phone, text)
        _to_inbox({"kind": "sms", "to": phone, "text": text})


@lru_cache
def get_notifier() -> Notifier:
    return LogNotifier()
