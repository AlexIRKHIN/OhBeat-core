"""Orders: creation with the Exclusive reservation (FR-15 … FR-19, FR-30, FR-32) and reading.

POST /orders is ONE database transaction:

    1. checks: billing details, prices the Artist saw, licenses, statuses           -> 409 ...
    2. INSERT orders (pending, snapshot of buyer and licensors) + order_items (price, fee)
    3. Exclusive:  UPDATE beats SET status = 'reserved' ... WHERE id = :beat AND status = 'active' RETURNING id
       Leases:     SELECT ... FOR SHARE  (FR-19: a beat reserved meanwhile blocks the order)
    4. contracts (offer_accept) for Basic / Premium / Trackout + audit_log
    5. COMMIT — or ROLLBACK of everything if any step fails

The UPDATE in step 3 is the real guard against two buyers: PostgreSQL locks the row, the second
transaction waits, re-reads `status`, finds 'reserved' and changes nothing (0 rows -> 409).
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.catalog.models import Beat, BeatFile, BeatPrice
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.errors import ApiError
from app.common.i18n import t
from app.common.storage import ObjectStorage
from app.contracts.draft import DraftItem, license_files, render_draft, sha256_text
from app.dictionaries.models import License
from app.orders.cart import unavailable_reason
from app.orders.models import Contract, Order, OrderItem, Payment
from app.orders.money import service_fee
from app.orders.schemas import OrderCreate, OrderCreated, OrderItemOut, OrderOut
from app.users.models import BillingProfile, ProducerAccount, Profile

BILLING_FIELDS = ("payer_type", "last_name", "first_name", "middle_name", "email", "phone",
                  "company_name", "inn", "legal_address")


def _billing_dict(row: BillingProfile) -> dict:
    return {f: getattr(row, f) for f in BILLING_FIELDS}


def _snapshot(db: Session, buyer: BillingProfile, producer_ids: set[int]) -> dict:
    """FR-32: data for the contract is copied into the order, so later edits do not change it.
    ASSUMPTION: GAP-8 — the licensors (Producers) are frozen too, not only the buyer."""
    licensors = {}
    for pid in sorted(producer_ids):
        billing = db.get(BillingProfile, pid)
        account = db.get(ProducerAccount, pid)
        licensors[str(pid)] = {
            **(_billing_dict(billing) if billing else {}),
            "user_id": pid,
            "display_name": db.get(Profile, pid).display_name,
            # RFC ПЭП §5: "Основание: соглашение о ПЭП от …"
            "pep_agreement_at": account.pep_agreement_at.isoformat() if account else None,
        }
    return {"buyer": {**_billing_dict(buyer), "user_id": buyer.user_id}, "licensors": licensors}


def _price_changed_detail(index: int, new_price: Decimal, beat_id: int, code: str) -> dict:
    return {
        "field": f"items[{index}].expected_price",
        "issue": t("price_changed_to", price=f"{new_price:.2f}"),
        "beat_id": beat_id,
        "license": code,
        "price": float(new_price),
    }


def create_order(db: Session, user_id: int, data: OrderCreate, ip: str | None) -> OrderCreated:
    settings = get_settings()
    licenses = {lic.code: lic for lic in db.scalars(select(License))}
    has_exclusive = any(licenses[i.license].is_exclusive for i in data.items)

    # --- 1. Checks ---
    billing = db.get(BillingProfile, user_id)
    if billing is None:
        raise ApiError(409, "BILLING_REQUIRED")  # REST API §2.5, §2.9
    if has_exclusive and not billing.phone:
        # RFC ПЭП §2: the signature code goes by SMS, so an order with Exclusive needs a phone
        raise ApiError(409, "BILLING_REQUIRED", [{"field": "phone", "issue": t("phone_required_for_exclusive")}])

    beats = {b.id: b for b in db.scalars(select(Beat).where(Beat.id.in_([i.beat_id for i in data.items])))}
    price_changes = []
    lines = []
    for index, item in enumerate(data.items):
        beat = beats.get(item.beat_id)
        license_row = licenses[item.license]
        price = db.get(BeatPrice, (item.beat_id, license_row.id)) if beat else None
        reason = unavailable_reason(beat, price, user_id)
        if reason:
            raise ApiError(409, reason, [{"field": f"items[{index}]", "issue": t(reason), "beat_id": item.beat_id}])
        if Decimal(price.price) != item.expected_price:
            price_changes.append(_price_changed_detail(index, Decimal(price.price), item.beat_id, item.license))
        lines.append((item, beat, license_row, Decimal(price.price)))
    if price_changes:
        # FR-15: the Artist sees the new prices and confirms the new total
        raise ApiError(409, "PRICE_CHANGED", price_changes)

    # --- 2. Order and items ---
    producers = {beat.producer_id for _, beat, _, _ in lines}
    order = Order(
        customer_id=user_id,
        status="pending",
        total_amount=sum((price + service_fee(price) for *_, price in lines), Decimal("0")),
        billing_snapshot=_snapshot(db, billing, producers),
    )
    db.add(order)
    db.flush()  # order.id is needed by the reservation

    items: list[tuple[OrderItem, Beat, License]] = []
    for _, beat, license_row, price in lines:
        item = OrderItem(
            order_id=order.id,
            beat_id=beat.id,
            license_id=license_row.id,
            producer_id=beat.producer_id,
            price_at_purchase=price,
            platform_fee=service_fee(price),  # FR-30: fixed in the order item
        )
        db.add(item)
        items.append((item, beat, license_row))
    db.flush()

    # --- 3. Reservation (FR-18) and the lease check (FR-19); sorted ids keep lock order stable ---
    reserved_until = None
    for item, beat, license_row in sorted(items, key=lambda x: x[1].id):
        if license_row.is_exclusive:
            row = db.execute(
                text(
                    "UPDATE beats SET status = 'reserved', reserved_order_id = :order_id, "
                    "reserved_until = now() + make_interval(mins => :ttl) "
                    "WHERE id = :beat_id AND status = 'active' RETURNING reserved_until"
                ),
                {"order_id": order.id, "beat_id": beat.id, "ttl": settings.reservation_ttl_minutes},
            ).first()
            if row is None:
                db.rollback()
                raise _conflict_by_actual_status(db, beat.id)
            reserved_until = min(filter(None, (reserved_until, row.reserved_until)))
        else:
            status = db.scalar(select(Beat.status).where(Beat.id == beat.id).with_for_update(read=True))
            if status != "active":
                db.rollback()
                raise _conflict_by_actual_status(db, beat.id)

    # --- 4. Contracts by offer acceptance for the leases (ASSUMPTION: GAP-30) ---
    now = datetime.now(UTC)
    for n, (item, beat, license_row) in enumerate(sorted(items, key=lambda x: x[0].id), start=1):
        if license_row.is_exclusive:
            continue  # signed with a one-time code (slice 4, RFC ПЭП §3)
        draft = render_draft(_draft_item(order, item, beat, license_row, n), order.billing_snapshot, "offer_accept")
        db.add(Contract(order_item_id=item.id, signature_type="offer_accept", draft_sha256=sha256_text(draft),
                        signer_ip=ip or "unknown", signed_at=now))

    items_total = sum((item.price_at_purchase for item, *_ in items), Decimal("0"))
    fee_total = sum((item.platform_fee for item, *_ in items), Decimal("0"))
    write_audit(db, action="order.created", entity="order", entity_id=order.id, actor_user_id=user_id, ip=ip,
                details={"items": len(items), "items_total": str(items_total), "service_fee": str(fee_total),
                         "total": str(order.total_amount), "exclusive": has_exclusive})
    if any(not lic.is_exclusive for *_, lic in items):
        write_audit(db, action="offer.accepted", entity="order", entity_id=order.id, actor_user_id=user_id, ip=ip)
    db.commit()

    return OrderCreated(
        order_id=order.id,
        status=order.status,
        items_total=items_total,
        service_fee=fee_total,
        total=order.total_amount,
        requires_signature=has_exclusive,
        reserved_until=reserved_until,
    )


def _conflict_by_actual_status(db: Session, beat_id: int) -> ApiError:
    """FR-18: the message follows the real status of the beat."""
    status = db.scalar(select(Beat.status).where(Beat.id == beat_id))
    code = {"reserved": "BEAT_RESERVED", "sold": "BEAT_SOLD"}.get(status, "BEAT_NOT_AVAILABLE")
    return ApiError(409, code, [{"field": "items", "issue": t(code), "beat_id": beat_id}])


def _draft_item(order: Order, item: OrderItem, beat: Beat, license_row: License, n: int) -> DraftItem:
    return DraftItem(
        order_id=order.id,
        number=f"{order.id}-{n}",  # ASSUMPTION: GAP-32
        beat={"id": beat.id, "title": beat.title, "bpm": beat.bpm, "musical_key": beat.musical_key},
        license_code=license_row.code,
        license_name=license_row.name,
        license_files=license_files(license_row.includes_mp3, license_row.includes_wav, license_row.includes_stems),
        price=Decimal(item.price_at_purchase),
        fee=Decimal(item.platform_fee),
        producer_id=item.producer_id,
    )


# --- Reading ---

def owned_order(db: Session, order_id: int, user_id: int, lock: bool = False) -> Order:
    query = select(Order).where(Order.id == order_id)
    order = db.scalar(query.with_for_update() if lock else query)
    if order is None:
        raise ApiError(404, "NOT_FOUND")
    if order.customer_id != user_id:
        raise ApiError(403, "FORBIDDEN")  # REST API §2.6: someone else's order
    return order


def get_order(db: Session, storage: ObjectStorage, order_id: int, user_id: int) -> OrderOut:
    order = owned_order(db, order_id, user_id)
    rows = db.execute(
        select(OrderItem, Beat, License)
        .join(Beat, Beat.id == OrderItem.beat_id)
        .join(License, License.id == OrderItem.license_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)
    ).all()
    covers = dict(db.execute(select(BeatFile.beat_id, BeatFile.storage_key).where(
        BeatFile.beat_id.in_([r.Beat.id for r in rows]), BeatFile.kind == "cover")).all())
    otp_signed = set(db.scalars(select(Contract.order_item_id).where(
        Contract.order_item_id.in_([r.OrderItem.id for r in rows]), Contract.signature_type == "otp")))
    snapshot_names = {pid: data.get("display_name", "") for pid, data in order.billing_snapshot["licensors"].items()}

    items = []
    for n, row in enumerate(rows, start=1):
        cover = covers.get(row.Beat.id)
        items.append(OrderItemOut(
            item_id=row.OrderItem.id,
            contract_number=f"{order.id}-{n}",
            beat_id=row.Beat.id,
            title=row.Beat.title,
            cover_url=storage.public_url(cover) if cover and cover.startswith("covers/") else None,
            producer=snapshot_names.get(str(row.OrderItem.producer_id), ""),
            license=row.License.code,
            price=row.OrderItem.price_at_purchase,
            service_fee=row.OrderItem.platform_fee,
        ))
    exclusive_items = [r.OrderItem.id for r in rows if r.License.is_exclusive]
    reserved_until = db.scalar(select(func.min(Beat.reserved_until)).where(Beat.reserved_order_id == order.id))
    last_payment = db.scalar(select(Payment.status).where(Payment.order_id == order.id).order_by(Payment.id.desc()))
    return OrderOut(
        order_id=order.id,
        status=order.status,
        created_at=order.created_at,
        items_total=sum((i.price for i in items), Decimal("0")),
        service_fee=sum((i.service_fee for i in items), Decimal("0")),
        total=order.total_amount,
        items=items,
        requires_signature=bool(exclusive_items),
        signed=all(i in otp_signed for i in exclusive_items),
        reserved_until=reserved_until,
        payment_status=last_payment,
    )
