"""Creating a payment for an order (FR-20, FR-21, FR-30, REST API §2.5).

    POST /orders/{id}/payments
      lock the order (a double click must not create two payments)
      checks: status pending → reservation alive → Exclusive signed
      an unfinished payment exists → its confirmation_url again (GAP-40)
      POST /v3/payments  {capture: false, amount, transfers per Producer, metadata}  with Idempotence-Key
      INSERT payments (provider id + key) after the answer (GAP-6) → COMMIT → confirmation_url
"""

import logging
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.models import Beat
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.errors import ApiError
from app.dictionaries.models import License
from app.orders.models import Contract, Order, OrderItem, Payment
from app.orders.money import rub
from app.orders.service import owned_order
from app.payments.gateway import GatewayRejected, GatewayUnavailable, PaymentGateway
from app.payments.schemas import PaymentCreated
from app.users.models import ProducerAccount

log = logging.getLogger("payments")


def transfers_for(db: Session, order: Order) -> tuple[list[dict], Decimal]:
    """FR-30, NFR-25, ASSUMPTION: GAP-41: one transfer per Producer — the sum of their prices;
    the fees stay with the platform. Σ transfers + Σ fees = the order total."""
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)).all()
    per_producer: dict[int, Decimal] = defaultdict(Decimal)
    for item in items:
        per_producer[item.producer_id] += Decimal(item.price_at_purchase)
    accounts = dict(db.execute(select(ProducerAccount.user_id, ProducerAccount.yookassa_account_id)
                               .where(ProducerAccount.user_id.in_(per_producer))).all())
    transfers = [{"account_id": accounts[pid], "amount": {"value": rub(amount), "currency": "RUB"}}
                 for pid, amount in sorted(per_producer.items())]
    fee = sum((Decimal(i.platform_fee) for i in items), Decimal("0"))
    return transfers, fee


def payment_body(db: Session, order: Order) -> dict:
    transfers, fee = transfers_for(db, order)
    return {
        "amount": {"value": rub(Decimal(order.total_amount)), "currency": "RUB"},
        "capture": False,  # FR-20: two stages — hold now, capture after the FR-23 check
        "confirmation": {"type": "redirect", "return_url": f"{get_settings().frontend_url}/orders/{order.id}/return"},
        "description": f"OhBeat, заказ № {order.id}",
        "metadata": {"order_id": str(order.id), "platform_fee": rub(fee)},
        "transfers": transfers,
    }


def create_payment(db: Session, gateway: PaymentGateway, order_id: int, user_id: int, ip: str | None) -> PaymentCreated:
    order = owned_order(db, order_id, user_id, lock=True)
    if order.status != "pending":
        raise ApiError(409, "INVALID_STATUS")  # paid, expired or canceled

    rows = db.execute(
        select(OrderItem, License, Beat)
        .join(License, License.id == OrderItem.license_id)
        .join(Beat, Beat.id == OrderItem.beat_id)
        .where(OrderItem.order_id == order.id)
    ).all()
    exclusive = [r for r in rows if r.License.is_exclusive]
    alive = db.scalar(select(func.count()).select_from(Beat).where(
        Beat.id.in_([r.Beat.id for r in exclusive]), Beat.status == "reserved",
        Beat.reserved_order_id == order.id, Beat.reserved_until > func.now()))
    if alive != len(exclusive):
        raise ApiError(410, "RESERVATION_EXPIRED")  # FR-18: the 15 minutes are over
    signed = set(db.scalars(select(Contract.order_item_id).where(
        Contract.order_item_id.in_([r.OrderItem.id for r in exclusive]), Contract.signature_type == "otp")))
    if any(r.OrderItem.id not in signed for r in exclusive):
        raise ApiError(428, "SIGNATURE_REQUIRED")  # RFC ПЭП: Exclusive is signed with a code first (slice 4)

    # GAP-40: an unfinished payment is reused; a new one only after the previous was canceled
    last = db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
    if last and last.status in ("waiting_for_capture", "succeeded"):
        raise ApiError(409, "INVALID_STATUS")  # the money is already held: the result is on its way
    if last and last.status == "pending":
        actual = _call(gateway.get_payment, str(last.provider_payment_id))
        if actual["status"] == "pending":
            return PaymentCreated(payment_id=str(last.provider_payment_id),
                                  confirmation_url=actual["confirmation"]["confirmation_url"])
        if actual["status"] != "canceled":
            raise ApiError(409, "INVALID_STATUS")  # held, the webhook has not been processed yet
        last.status = "canceled"  # declined, the webhook is late: a new attempt is allowed (FR-25)

    key = str(uuid.uuid4())  # ASSUMPTION: GAP-6 — kept in memory for the retries, saved with the answer
    created = _call(gateway.create_payment, key, payment_body(db, order))
    db.add(Payment(order_id=order.id, provider_payment_id=uuid.UUID(created["id"]), idempotence_key=uuid.UUID(key),
                   status=created["status"], amount=order.total_amount))
    write_audit(db, action="payment.created", entity="order", entity_id=order.id, actor_user_id=user_id, ip=ip,
                details={"payment_id": created["id"], "amount": str(order.total_amount)})
    db.commit()
    return PaymentCreated(payment_id=created["id"], confirmation_url=created["confirmation"]["confirmation_url"])


def _call(fn, *args):
    try:
        return fn(*args)
    except GatewayUnavailable:
        # FR-21: the reservation stays (nothing was changed in the database)
        raise ApiError(503, "PAYMENT_PROVIDER_UNAVAILABLE") from None
    except GatewayRejected as error:
        log.error("YooKassa refused the request: %s", error)  # a bug of ours, e.g. a wrong split
        raise ApiError(503, "PAYMENT_PROVIDER_UNAVAILABLE") from None
