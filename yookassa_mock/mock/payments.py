"""Payment logic of the mock: the two-stage payment of YooKassa API v3 with the split for marketplaces.

    pending ──(buyer pays)──► waiting_for_capture ──capture──► succeeded
       │                             │
       └──(bank declines)──► canceled ◄──cancel / hold expired

Events sent as webhooks: payment.waiting_for_capture, payment.succeeded, payment.canceled.
"""

import os
import uuid
from decimal import Decimal, InvalidOperation

from mock import store, webhooks


class ApiProblem(Exception):
    """An error answer in the YooKassa format: {"type": "error", "code", "description", "parameter"}."""

    def __init__(self, status_code: int, code: str, description: str, parameter: str | None = None):
        super().__init__(description)
        self.status_code = status_code
        self.body = {"type": "error", "id": str(uuid.uuid4()), "code": code, "description": description}
        if parameter:
            self.body["parameter"] = parameter


def public_url() -> str:
    """Address of the mock as the BROWSER sees it: the payment page opens there."""
    return os.environ.get("MOCK_PUBLIC_URL", "http://localhost:8100")


def _money(value, parameter: str) -> Decimal:
    if not isinstance(value, dict) or value.get("currency") != "RUB":
        raise ApiProblem(400, "invalid_request", "Amount must be {value, currency: RUB}", parameter)
    try:
        amount = Decimal(str(value.get("value")))
    except (InvalidOperation, TypeError):
        raise ApiProblem(400, "invalid_request", "Amount value is not a number", parameter) from None
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ApiProblem(400, "invalid_request", "Amount must be positive with at most two decimals", parameter)
    return amount


def _rub(amount: Decimal) -> dict:
    return {"value": f"{amount:.2f}", "currency": "RUB"}


def create(request: dict) -> dict:
    amount = _money(request.get("amount"), "amount")
    confirmation = request.get("confirmation") or {}
    if confirmation.get("type") != "redirect" or not confirmation.get("return_url"):
        raise ApiProblem(400, "invalid_request", "confirmation must be {type: redirect, return_url}", "confirmation")
    metadata = request.get("metadata") or {}

    # Split for marketplaces: every seller gets its transfer, the rest stays with the platform.
    # ASSUMPTION: GAP-41 — the platform part comes in metadata.platform_fee, so the mock can check
    # Σ transfers + fee = amount and refuse a wrong split, as the real service refuses an impossible one.
    transfers = []
    for i, t in enumerate(request.get("transfers") or []):
        if not isinstance(t, dict) or not t.get("account_id"):
            raise ApiProblem(400, "invalid_request", "Transfer needs account_id", f"transfers[{i}].account_id")
        transfers.append({"account_id": str(t["account_id"]), "amount": _rub(_money(t.get("amount"), f"transfers[{i}].amount")),
                          "status": "pending"})
    if transfers:
        raw_fee = metadata.get("platform_fee")
        fee = Decimal("0") if raw_fee in (None, "", "0", "0.00") else _money({"value": raw_fee, "currency": "RUB"}, "metadata.platform_fee")
        split = sum((Decimal(t["amount"]["value"]) for t in transfers), Decimal("0"))
        if split + fee != amount:
            raise ApiProblem(400, "invalid_request",
                             f"Sum of transfers {split:.2f} + platform fee {fee:.2f} != amount {amount:.2f}", "transfers")

    payment_id = str(uuid.uuid4())
    payment = {
        "id": payment_id,
        "status": "pending",
        "paid": False,
        "amount": _rub(amount),
        "description": request.get("description"),
        "recipient": {"account_id": os.environ.get("YOOKASSA_SHOP_ID", "000000"), "gateway_id": "mock"},
        "created_at": store.now_iso(),
        "confirmation": {
            "type": "redirect",
            "return_url": confirmation["return_url"],
            "confirmation_url": f"{public_url()}/checkout/{payment_id}",
        },
        "test": True,
        "refundable": False,
        "metadata": metadata,
        "transfers": transfers,
        "capture": bool(request.get("capture", False)),
    }
    store.save_payment(payment)
    return payment


def get(payment_id: str) -> dict:
    payment = store.get_payment(payment_id)
    if payment is None:
        raise ApiProblem(404, "not_found", "Payment not found")
    return payment


def _cancel_details(party: str, reason: str) -> dict:
    return {"party": party, "reason": reason}


def buyer_paid(payment_id: str, outcome: str) -> dict:
    """The buyer's choice on the payment page: success (money held), decline, or success without a webhook."""
    with store.locked():
        payment = get(payment_id)
        if payment["status"] != "pending":
            return payment
        if outcome == "decline":
            payment.update(status="canceled", cancellation_details=_cancel_details("payment_network", "insufficient_funds"))
            for transfer in payment["transfers"]:
                transfer["status"] = "canceled"
            event = "payment.canceled"
        elif payment.get("capture"):
            payment.update(status="succeeded", paid=True, captured_at=store.now_iso())
            event = "payment.succeeded"
        else:
            # The money is held; in reality the hold lasts days, the panel can end it ("hold expired")
            payment.update(status="waiting_for_capture", paid=True)
            event = "payment.waiting_for_capture"
        payment.pop("confirmation", None)  # the payment page is used up
        store.save_payment(payment)
    if outcome != "silent":
        webhooks.send(payment, event)
    return payment


def capture(payment_id: str, request: dict) -> dict:
    with store.locked():
        payment = get(payment_id)
        if payment["status"] == "succeeded":
            return payment
        if payment["status"] != "waiting_for_capture":
            raise ApiProblem(400, "invalid_request", f"Payment is {payment['status']}, capture is not possible")
        if request.get("amount") and _money(request["amount"], "amount") != Decimal(payment["amount"]["value"]):
            raise ApiProblem(400, "invalid_request", "Partial capture is not supported by the mock", "amount")
        payment.update(status="succeeded", captured_at=store.now_iso())
        for transfer in payment["transfers"]:
            transfer["status"] = "succeeded"  # FR-30: the sellers get their parts after a successful payment
        store.save_payment(payment)
    webhooks.send(payment, "payment.succeeded")
    return payment


def cancel(payment_id: str, party: str = "merchant", reason: str = "canceled_by_merchant") -> dict:
    with store.locked():
        payment = get(payment_id)
        if payment["status"] == "canceled":
            return payment
        if payment["status"] == "succeeded":
            raise ApiProblem(400, "invalid_request", "Payment is succeeded, cancel is not possible")
        payment.update(status="canceled", cancellation_details=_cancel_details(party, reason))
        for transfer in payment["transfers"]:
            transfer["status"] = "canceled"
        payment.pop("confirmation", None)
        store.save_payment(payment)
    webhooks.send(payment, "payment.canceled")
    return payment
