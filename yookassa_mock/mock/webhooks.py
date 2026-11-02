"""Webhook notifications, delivered the way YooKassa does it.

Any answer except 200 (or no answer) counts as a failure, and the notification is sent again
after a pause: 1, 2, 4, 8, 16 seconds (the real service keeps trying for 24 hours; locally a short
series is enough to see the behaviour). Every attempt is written to `deliveries` for the panel.
"""

import logging
import os
import threading
import time

import httpx

from mock import store

log = logging.getLogger("yookassa-mock.webhooks")

RETRY_DELAYS = [float(x) for x in os.environ.get("MOCK_WEBHOOK_RETRY_DELAYS", "1,2,4,8,16").split(",") if x]


def webhook_url() -> str:
    return os.environ.get("MOCK_WEBHOOK_URL", "http://api:8000/v1/payments/webhook")


def body(payment: dict, event: str) -> dict:
    return {"type": "notification", "event": event, "object": payment}


def deliver(payment: dict, event: str) -> bool:
    """Sends one notification with retries. Blocks; run it in a thread (see `send`)."""
    delay = float(store.get_setting("webhook_delay_seconds", "0"))
    if delay:
        time.sleep(delay)
    for attempt, pause in enumerate([0.0, *RETRY_DELAYS], start=1):
        if pause:
            time.sleep(pause)
        try:
            response = httpx.post(webhook_url(), json=body(payment, event), timeout=10)
            result = str(response.status_code)
            ok = response.status_code == 200
        except httpx.HTTPError as error:
            result, ok = f"no answer: {type(error).__name__}", False
        store.log_delivery(payment["id"], event, attempt, result)
        log.info("webhook %s %s attempt %s -> %s", event, payment["id"], attempt, result)
        if ok:
            return True
    log.warning("webhook %s %s given up after %s attempts", event, payment["id"], len(RETRY_DELAYS) + 1)
    return False


def send(payment: dict, event: str) -> None:
    """Fire and forget, like YooKassa: the API answer does not wait for the notification."""
    threading.Thread(target=deliver, args=(dict(payment), event), daemon=True).start()
