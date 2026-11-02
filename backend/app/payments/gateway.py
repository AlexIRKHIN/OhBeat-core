"""Payment gateway YooKassa behind an interface (System_Architecture.md: external systems).

Core API talks to YooKassa only through `PaymentGateway`. The real implementation is an HTTP client
of API v3 (locally it reaches the mock); tests put a fake one in its place.

Two kinds of failure matter for the business rules:
* `GatewayUnavailable` — no answer, timeout, 5xx or 429 after all retries. Nothing is known about
  the result: the same request may be repeated later with the same Idempotence-Key (FR-21, GAP-35).
* `GatewayRejected` — YooKassa answered 4xx: the request is final-wrong, repeating will not help (GAP-37).
"""

import logging
import time
import uuid
from functools import lru_cache
from typing import Protocol

import httpx

from app.common.config import get_settings

log = logging.getLogger("payments.gateway")

# Keys of capture / cancel are derived from the payment, so every repetition — after a crash, by the
# scheduler, by a second webhook — sends the SAME key and YooKassa does the operation once (GAP-35).
_KEYS = uuid.UUID("6f1d3c7e-2b0a-4d43-9e57-0b0e5c7a1f42")


def settle_key(operation: str, provider_payment_id: str) -> str:
    return str(uuid.uuid5(_KEYS, f"{operation}:{provider_payment_id}"))


class GatewayUnavailable(Exception):
    pass


class GatewayRejected(Exception):
    def __init__(self, status_code: int, body: dict):
        super().__init__(f"{status_code}: {body}")
        self.status_code = status_code
        self.body = body


class PaymentGateway(Protocol):
    def create_payment(self, idempotence_key: str, body: dict) -> dict: ...

    def get_payment(self, provider_payment_id: str) -> dict: ...

    def capture(self, provider_payment_id: str, amount: dict) -> dict: ...

    def cancel(self, provider_payment_id: str) -> dict: ...


class YooKassaGateway:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.yookassa_api_url.rstrip("/")
        self.auth = (s.yookassa_shop_id, s.yookassa_secret_key)
        self.timeout = s.yookassa_timeout_seconds
        self.pauses = [float(p) for p in s.yookassa_retry_pauses.split(",") if p.strip()]

    def _request(self, method: str, path: str, key: str | None = None, body: dict | None = None) -> dict:
        """1 attempt + retries (GAP-62). The Idempotence-Key stays the same in every attempt (FR-21)."""
        headers = {"Idempotence-Key": key} if key else {}
        for attempt, pause in enumerate([0.0, *self.pauses], start=1):
            if pause:
                time.sleep(pause)
            try:
                response = httpx.request(method, f"{self.base}{path}", json=body, headers=headers,
                                         auth=self.auth, timeout=self.timeout)
            except httpx.HTTPError as error:
                log.warning("%s %s attempt %s: %s", method, path, attempt, type(error).__name__)
                continue
            if response.status_code == 200:
                return response.json()
            if response.status_code >= 500 or response.status_code == 429:
                log.warning("%s %s attempt %s: HTTP %s", method, path, attempt, response.status_code)
                continue
            raise GatewayRejected(response.status_code, _json(response))
        raise GatewayUnavailable(f"{method} {path}: no answer after {len(self.pauses) + 1} attempts")

    def create_payment(self, idempotence_key: str, body: dict) -> dict:
        return self._request("POST", "/payments", idempotence_key, body)

    def get_payment(self, provider_payment_id: str) -> dict:
        return self._request("GET", f"/payments/{provider_payment_id}")

    def capture(self, provider_payment_id: str, amount: dict) -> dict:
        return self._request("POST", f"/payments/{provider_payment_id}/capture",
                             settle_key("capture", provider_payment_id), {"amount": amount})

    def cancel(self, provider_payment_id: str) -> dict:
        return self._request("POST", f"/payments/{provider_payment_id}/cancel",
                             settle_key("cancel", provider_payment_id), {})


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {"raw": response.text[:500]}
    return data if isinstance(data, dict) else {"raw": data}


@lru_cache
def get_gateway() -> PaymentGateway:
    return YooKassaGateway()
