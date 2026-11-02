"""What happens when YooKassa reports a payment status (FR-22 … FR-25, REST API §2.7).

    webhook ──► GET /v3/payments/{id}  (trust YooKassa, not the body; FR-22, GAP-38)
            ──► ONE transaction:
                  INSERT payment_events (payment, event)  — a duplicate stops here: 200, nothing else
                  waiting_for_capture → FR-23 check: Exclusive sold / leases not sold → decision
                  succeeded           → order paid, cart cleaned, audit (FR-24)
                  canceled            → payment canceled; a sale made for it is undone (FR-25, GAP-37)
            ──► COMMIT ──► 200
            ──► after the answer: capture or cancel, emails (GAP-35, GAP-36)

The decision "capture or cancel" can always be derived from the database again (`decision`), so the
scheduler finishes payments left in the hold when Core API crashed after the commit (GAP-35).
"""

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import Beat
from app.common.audit import write_audit
from app.common.config import get_settings
from app.dictionaries.models import License
from app.orders.models import CartItem, Order, OrderItem, Payment, PaymentEvent
from app.payments.gateway import GatewayRejected, GatewayUnavailable, PaymentGateway
from app.users.models import User

log = logging.getLogger("payments.events")

# Why an order is canceled at the FR-23 check — shown to the Artist and written to the Audit Log
REASON_TEXT = {
    "BEAT_SOLD": "эксклюзивные права на бит уже проданы другому покупателю",
    "BEAT_RESERVED": "бит в это время оформлял другой покупатель",
    "BEAT_NOT_AVAILABLE": "бит снят с продажи",
    "AMOUNT_MISMATCH": "сумма платежа не совпала с суммой заказа",
    "CAPTURE_FAILED": "банк не подтвердил списание",
}


@dataclass
class Followups:
    """Calls to make AFTER the commit: external systems are never called inside a transaction."""

    settle: list[tuple[str, str, dict]] = field(default_factory=list)  # (capture|cancel, provider id, amount)
    emails: list[tuple[str, str, str]] = field(default_factory=list)  # (to, subject, body)

    def extend(self, other: "Followups") -> None:
        self.settle += other.settle
        self.emails += other.emails


def process(db: Session, gateway: PaymentGateway, provider_payment_id: str) -> Followups:
    """Applies the ACTUAL status of a payment. Raises GatewayUnavailable → the webhook answers 500."""
    try:
        payment_uuid = uuid.UUID(provider_payment_id)
    except ValueError:
        log.warning("webhook with a malformed payment id %r ignored", provider_payment_id)
        return Followups()
    payment = db.scalar(select(Payment).where(Payment.provider_payment_id == payment_uuid))
    if payment is None:
        # ASSUMPTION: GAP-7 — payment_events references payments, so the event cannot be stored
        log.warning("webhook for unknown payment %s ignored", provider_payment_id)
        return Followups()

    actual = gateway.get_payment(provider_payment_id)  # FR-22: verify, do not trust the body
    status = actual.get("status")
    if status not in ("waiting_for_capture", "succeeded", "canceled"):
        return Followups()  # still pending: nothing happened yet

    # FR-22: one processing per (payment, event). ASSUMPTION: GAP-67 — the event is named by the actual
    # status, so a late "waiting_for_capture" arriving after "succeeded" is a duplicate of nothing new.
    event = f"payment.{status}"
    inserted = db.execute(
        insert(PaymentEvent).values(provider_payment_id=payment_uuid, event=event, payload=actual)
        .on_conflict_do_nothing(index_elements=["provider_payment_id", "event"]).returning(PaymentEvent.id)
    ).scalar()
    if inserted is None:
        db.rollback()
        log.info("%s for %s already processed: duplicate", event, provider_payment_id)
        return Followups()

    # Lock order: beats first, then the order — the same as the FR-29 statement (beats → orders),
    # otherwise the webhook and the scheduler could wait for each other forever (a deadlock)
    db.execute(select(Beat.id).where(Beat.id.in_(select(OrderItem.beat_id).where(OrderItem.order_id == payment.order_id)))
               .order_by(Beat.id).with_for_update())
    order = db.scalar(select(Order).where(Order.id == payment.order_id).with_for_update())
    db.refresh(payment, with_for_update=True)
    handler = {"waiting_for_capture": _on_hold, "succeeded": _on_succeeded, "canceled": _on_canceled}[status]
    followups = handler(db, payment, order, actual)
    write_audit(db, action=event, entity="order", entity_id=order.id, actor_user_id=None, ip=None,
                details={"payment_id": provider_payment_id, "amount": actual.get("amount", {}).get("value"),
                         "order_status": order.status,
                         "cancellation": (actual.get("cancellation_details") or {}).get("reason")})
    db.commit()
    log.info("%s for order %s processed, order is %s", event, order.id, order.status)
    return followups


# --- waiting_for_capture: FR-23 ---

def _on_hold(db: Session, payment: Payment, order: Order, actual: dict) -> Followups:
    payment.status = "waiting_for_capture"
    reason = None
    if not _amount_matches(payment, order, actual):
        reason = "AMOUNT_MISMATCH"  # ASSUMPTION: GAP-38, GAP-67 — the order is canceled too
    elif order.status in ("pending", "expired"):
        reason = _sell(db, order)  # FR-24: an expired order may still be paid if the check passes
    # order paid by another payment or already canceled: this payment is simply released

    if reason:
        _cancel_order(db, order, reason)
    followups = Followups()
    followups.settle.append((decision(db, payment, order, actual), str(payment.provider_payment_id), actual["amount"]))
    if reason:
        followups.emails.append(_canceled_email(db, order, reason))
    return followups


def _amount_matches(payment: Payment, order: Order, actual: dict) -> bool:
    amount = actual.get("amount") or {}
    return amount.get("currency") == "RUB" and Decimal(amount.get("value", "0")) == Decimal(order.total_amount) == Decimal(payment.amount)


def _sell(db: Session, order: Order) -> str | None:
    """FR-23 in a savepoint: either every item can be sold, or nothing changes."""
    rows = db.execute(
        select(OrderItem.beat_id, License.is_exclusive)
        .join(License, License.id == OrderItem.license_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.beat_id)  # the same lock order everywhere: no deadlocks
    ).all()
    savepoint = db.begin_nested()
    for beat_id, is_exclusive in rows:
        if is_exclusive:
            sold = db.execute(
                text("UPDATE beats SET status = 'sold', reserved_order_id = NULL, reserved_until = NULL "
                     "WHERE id = :beat AND (status = 'active' OR (status = 'reserved' AND reserved_order_id = :order)) "
                     "RETURNING id"),
                {"beat": beat_id, "order": order.id},
            ).first()
            if sold is None:
                status = db.scalar(select(Beat.status).where(Beat.id == beat_id))
                savepoint.rollback()
                return {"sold": "BEAT_SOLD", "reserved": "BEAT_RESERVED"}.get(status, "BEAT_NOT_AVAILABLE")
        else:
            # ASSUMPTION: GAP-39 — only `sold` blocks a lease; hidden or deleted after the order does not
            status = db.scalar(select(Beat.status).where(Beat.id == beat_id).with_for_update(read=True))
            if status == "sold":
                savepoint.rollback()
                return "BEAT_SOLD"
    savepoint.commit()
    return None


def _cancel_order(db: Session, order: Order, reason: str) -> None:
    """GAP-36: the order is canceled in the webhook transaction; `cancel` goes to YooKassa after the commit."""
    if order.status not in ("pending", "expired"):
        return
    order.status = "canceled"
    db.execute(text("UPDATE beats SET status = 'active', reserved_order_id = NULL, reserved_until = NULL "
                    "WHERE reserved_order_id = :order AND status = 'reserved'"), {"order": order.id})
    write_audit(db, action="order.canceled", entity="order", entity_id=order.id, actor_user_id=None, ip=None,
                details={"reason": reason})


def decision(db: Session, payment: Payment, order: Order, actual: dict) -> str:
    """Capture or cancel, from the data alone (GAP-35): the same answer at any later moment."""
    if not _amount_matches(payment, order, actual) or order.status == "canceled":
        return "cancel"
    if order.status == "paid":  # ASSUMPTION: GAP-68 — a second hold of a paid order is released
        other_paid = db.scalar(select(func.count()).select_from(Payment).where(
            Payment.order_id == order.id, Payment.status == "succeeded", Payment.id != payment.id))
        return "cancel" if other_paid else "capture"
    return "capture"  # pending / expired with the FR-23 check passed


# --- succeeded: FR-24 ---

def _on_succeeded(db: Session, payment: Payment, order: Order, actual: dict) -> Followups:
    payment.status = "succeeded"
    followups = Followups()
    if order.status not in ("pending", "expired"):
        # We never capture for a canceled order and cancel a second payment of a paid one, so this
        # means money was taken twice; refunds are outside the MVP — leave a trace for the admin.
        log.error("payment %s succeeded for order %s in status %s", payment.provider_payment_id, order.id, order.status)
        write_audit(db, action="payment.unexpected_success", entity="order", entity_id=order.id,
                    actor_user_id=None, ip=None, details={"payment_id": str(payment.provider_payment_id)})
        return followups

    order.status = "paid"
    beats = [b for b, in db.execute(select(OrderItem.beat_id).where(OrderItem.order_id == order.id))]
    # a reservation of this order cannot outlive the payment
    db.execute(text("UPDATE beats SET status = 'active', reserved_order_id = NULL, reserved_until = NULL "
                    "WHERE reserved_order_id = :order AND status = 'reserved'"), {"order": order.id})
    # ASSUMPTION: GAP-29 — bought beats leave the cart when the order is paid
    db.execute(delete(CartItem).where(CartItem.user_id == order.customer_id, CartItem.beat_id.in_(beats)))
    write_audit(db, action="order.paid", entity="order", entity_id=order.id, actor_user_id=None, ip=None,
                details={"total": str(order.total_amount)})
    followups.emails += _sale_emails(db, order)
    return followups


# --- canceled: FR-25, GAP-37 ---

def _on_canceled(db: Session, payment: Payment, order: Order, actual: dict) -> Followups:
    was_held = payment.status == "waiting_for_capture"
    payment.status = "canceled"
    followups = Followups()
    if was_held and order.status in ("pending", "expired"):
        # The FR-23 check passed (the beats are sold for this order), but the money was never taken:
        # capture failed finally or the hold expired. FR-23: the beats go back on sale.
        db.execute(text(
            "UPDATE beats SET status = 'active' WHERE status = 'sold' AND id IN ("
            " SELECT oi.beat_id FROM order_items oi JOIN licenses l ON l.id = oi.license_id"
            " WHERE oi.order_id = :order AND l.is_exclusive)"), {"order": order.id})
        _cancel_order(db, order, "CAPTURE_FAILED")
        followups.emails.append(_canceled_email(db, order, "CAPTURE_FAILED"))
    # A bank decline before the hold: the order stays pending, the Artist may pay again (FR-25)
    return followups


# --- After the commit ---

def run_followups(db_factory, gateway: PaymentGateway, followups: Followups) -> None:
    """capture / cancel and emails. Errors here never undo the committed decision:
    a network failure is retried by the scheduler (GAP-35), a final refusal of capture is GAP-37."""
    from app.notifications.service import get_notifier

    for operation, provider_payment_id, amount in followups.settle:
        try:
            if operation == "capture":
                gateway.capture(provider_payment_id, amount)
            else:
                gateway.cancel(provider_payment_id)
            log.info("%s of %s done", operation, provider_payment_id)
        except GatewayUnavailable:
            log.warning("%s of %s: YooKassa unavailable, the scheduler will retry", operation, provider_payment_id)
        except GatewayRejected as error:
            log.error("%s of %s refused finally: %s", operation, provider_payment_id, error)
            if operation == "capture":
                _capture_failed(db_factory, gateway, provider_payment_id)
    for to, subject, body in followups.emails:
        get_notifier().send_email(to, subject, body)


def _capture_failed(db_factory, gateway: PaymentGateway, provider_payment_id: str) -> None:
    """GAP-37: release the hold if it still exists, then apply the final status (canceled)."""
    try:
        gateway.cancel(provider_payment_id)
    except (GatewayRejected, GatewayUnavailable) as error:
        log.warning("cancel after failed capture of %s: %s", provider_payment_id, error)
    with db_factory() as db:
        followups = process(db, gateway, provider_payment_id)
    run_followups(db_factory, gateway, followups)


# --- The scheduler: payments stuck in the hold (GAP-35) ---

def settle_stuck_payments(db: Session, gateway: PaymentGateway | None = None, db_factory=None) -> int:
    from app.common.db import get_session_factory
    from app.payments.gateway import get_gateway

    gateway = gateway or get_gateway()
    db_factory = db_factory or get_session_factory()
    stuck = db.scalars(
        select(Payment).where(
            Payment.status == "waiting_for_capture",
            select(PaymentEvent.id).where(
                PaymentEvent.provider_payment_id == Payment.provider_payment_id,
                PaymentEvent.event == "payment.waiting_for_capture",
                PaymentEvent.received_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, get_settings().payment_settle_after_seconds),
            ).exists(),
        )
    ).all()
    db.rollback()  # do not keep a transaction open while calling YooKassa
    for payment in stuck:
        provider_id = str(payment.provider_payment_id)
        try:
            actual = gateway.get_payment(provider_id)
            if actual["status"] == "waiting_for_capture":
                with db_factory() as session:
                    p = session.get(Payment, payment.id)
                    order = session.get(Order, p.order_id)
                    followups = Followups(settle=[(decision(session, p, order, actual), provider_id, actual["amount"])])
            else:  # settled meanwhile, only the webhook is missing: apply the actual status
                with db_factory() as session:
                    followups = process(session, gateway, provider_id)
            log.info("stuck payment %s: %s", provider_id, followups.settle or "status applied")
            run_followups(db_factory, gateway, followups)
        except GatewayUnavailable:
            log.warning("stuck payment %s: YooKassa unavailable, next minute", provider_id)
    return len(stuck)


# --- Emails (GAP-55: to users.email, sent after the commit) ---

def _email_of(db: Session, user_id: int) -> str:
    return db.scalar(select(User.email).where(User.id == user_id))


def _canceled_email(db: Session, order: Order, reason: str) -> tuple[str, str, str]:
    link = f"{get_settings().frontend_url}/orders/{order.id}"
    return (_email_of(db, order.customer_id), f"Заказ № {order.id} отменён",
            f"Заказ № {order.id} отменён: {REASON_TEXT[reason]}. Деньги не списаны, блокировка на карте снята.\n{link}")


def _sale_emails(db: Session, order: Order) -> list[tuple[str, str, str]]:
    """FR-24: every Producer of the order learns about the sale; the Artist gets a confirmation."""
    rows = db.execute(
        select(OrderItem.producer_id, Beat.title, License.name, OrderItem.price_at_purchase)
        .join(Beat, Beat.id == OrderItem.beat_id).join(License, License.id == OrderItem.license_id)
        .where(OrderItem.order_id == order.id).order_by(OrderItem.id)
    ).all()
    emails = []
    for producer_id in sorted({r.producer_id for r in rows}):
        lines = [f"«{r.title}», {r.name}: {r.price_at_purchase} ₽" for r in rows if r.producer_id == producer_id]
        emails.append((_email_of(db, producer_id), "Продажа на OhBeat",
                       "Ваши биты купили (заказ № %s):\n%s" % (order.id, "\n".join(lines))))
    purchases = f"{get_settings().frontend_url}/purchases"
    # FR-27: the email links to "My purchases", not to the files (links live 1 hour, NFR-8)
    emails.append((_email_of(db, order.customer_id), f"Заказ № {order.id} оплачен",
                   f"Оплата прошла. Файлы и договоры — в разделе «Мои покупки»: {purchases}"))
    return emails
