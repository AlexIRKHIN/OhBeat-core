"""A fake YooKassa for tests: the same contract as the mock, in memory, with switches for failures."""

import threading
import uuid
from decimal import Decimal

from app.payments.gateway import GatewayRejected, GatewayUnavailable


class FakeGateway:
    def __init__(self) -> None:
        self.payments: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []  # (operation, payment id)
        self.created_bodies: list[dict] = []
        self.fail: dict[str, str] = {}  # operation -> "unavailable" | "rejected"
        self._lock = threading.Lock()

    def _maybe_fail(self, operation: str) -> None:
        mode = self.fail.get(operation)
        if mode == "unavailable":
            raise GatewayUnavailable(operation)
        if mode == "rejected":
            raise GatewayRejected(400, {"code": "invalid_request"})

    # --- PaymentGateway ---

    def create_payment(self, idempotence_key: str, body: dict) -> dict:
        self._maybe_fail("create")
        with self._lock:
            if idempotence_key in self.by_key:
                return dict(self.payments[self.by_key[idempotence_key]])
            split = sum(Decimal(t["amount"]["value"]) for t in body["transfers"])
            if split + Decimal(body["metadata"]["platform_fee"]) != Decimal(body["amount"]["value"]):
                raise GatewayRejected(400, {"code": "invalid_request", "parameter": "transfers"})
            payment_id = str(uuid.uuid4())
            self.payments[payment_id] = {
                "id": payment_id, "status": "pending", "paid": False, "amount": body["amount"],
                "metadata": body["metadata"], "transfers": body["transfers"],
                "confirmation": {"type": "redirect", "confirmation_url": f"http://mock/checkout/{payment_id}"},
            }
            self.by_key[idempotence_key] = payment_id
            self.created_bodies.append(body)
            self.calls.append(("create", payment_id))
            return dict(self.payments[payment_id])

    def get_payment(self, provider_payment_id: str) -> dict:
        self._maybe_fail("get")
        return dict(self.payments[provider_payment_id])

    def capture(self, provider_payment_id: str, amount: dict) -> dict:
        with self._lock:
            self.calls.append(("capture", provider_payment_id))
        self._maybe_fail("capture")
        payment = self.payments[provider_payment_id]
        if payment["status"] == "waiting_for_capture":
            payment["status"] = "succeeded"
        elif payment["status"] != "succeeded":
            raise GatewayRejected(400, {"code": "invalid_request"})
        return dict(payment)

    def cancel(self, provider_payment_id: str) -> dict:
        with self._lock:
            self.calls.append(("cancel", provider_payment_id))
        self._maybe_fail("cancel")
        payment = self.payments[provider_payment_id]
        if payment["status"] in ("pending", "waiting_for_capture"):
            payment.update(status="canceled", cancellation_details={"party": "merchant", "reason": "canceled_by_merchant"})
        return dict(payment)

    # --- What the buyer and YooKassa do ---

    def hold(self, payment_id: str) -> None:
        self.payments[payment_id].update(status="waiting_for_capture", paid=True)

    def decline(self, payment_id: str) -> None:
        self.payments[payment_id].update(status="canceled", cancellation_details={"party": "payment_network", "reason": "insufficient_funds"})

    def expire_hold(self, payment_id: str) -> None:
        self.payments[payment_id].update(status="canceled", cancellation_details={"party": "yoo_money", "reason": "expired_on_capture"})

    def count(self, operation: str, payment_id: str | None = None) -> int:
        return sum(1 for op, pid in self.calls if op == operation and (payment_id is None or pid == payment_id))
