"""What the Artist bought and what the Producer sold (FR-28, REST API §2.6, §2.10, §2.12, UC-14).

Links to files are made on every request and live at most one hour (NFR-8); they are stored
nowhere, so an old link from an email or a log stops working by itself.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.models import Beat, BeatFile
from app.common.config import get_settings
from app.common.errors import ApiError, field_error
from app.common.storage import ObjectStorage
from app.contracts.issue import MSK, contract_number
from app.dictionaries.models import License
from app.orders.models import Contract, Order, OrderItem, Payment, PaymentEvent
from app.orders.service import owned_order
from app.purchases.schemas import DownloadFile, DownloadItem, Downloads, Purchase, Purchases, Sale, Sales

LINK_TTL_MAX = 3600  # NFR-8: not longer than an hour, whatever the settings say

# kind in the answer -> kind in beat_files, the license flag and the file name (REST API §2.6)
FILE_KINDS = (
    ("mp3", "clean_mp3", "includes_mp3", "mp3"),
    ("wav", "master", "includes_wav", "wav"),
    ("stems", "stems", "includes_stems", "zip"),
)


def paid_at_column():
    """ASSUMPTION: GAP-64 — the payment date is when payment.succeeded of the order was received."""
    return (
        select(func.min(PaymentEvent.received_at))
        .join(Payment, Payment.provider_payment_id == PaymentEvent.provider_payment_id)
        .where(Payment.order_id == Order.id, PaymentEvent.event == "payment.succeeded")
        .correlate(Order)
        .scalar_subquery()
    )


def downloads(db: Session, storage: ObjectStorage, order_id: int, user_id: int) -> Downloads:
    order = owned_order(db, order_id, user_id)  # 404 / 403 for someone else's order
    if order.status != "paid":
        raise ApiError(409, "ORDER_NOT_PAID")
    ttl = min(get_settings().download_link_ttl_seconds, LINK_TTL_MAX)
    rows = db.execute(
        select(OrderItem, License, Contract.pdf_key)
        .join(License, License.id == OrderItem.license_id)
        .outerjoin(Contract, Contract.order_item_id == OrderItem.id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)
    ).all()
    stored = {(f.beat_id, f.kind): f.storage_key for f in db.scalars(
        select(BeatFile).where(BeatFile.beat_id.in_([r.OrderItem.beat_id for r in rows])))}
    bucket = get_settings().bucket_private

    items = []
    for n, row in enumerate(rows, start=1):
        number = contract_number(order.id, n)
        beat_id = row.OrderItem.beat_id
        files = []
        for kind, file_kind, flag, ext in FILE_KINDS:
            key = stored.get((beat_id, file_kind))
            if getattr(row.License, flag) and key:
                files.append(DownloadFile(kind=kind, url=storage.presigned_get(
                    bucket, key, ttl, f"ohbeat-{beat_id}-{row.License.code}.{ext}")))
        if row.pdf_key:
            files.append(DownloadFile(kind="contract", url=storage.presigned_get(
                bucket, row.pdf_key, ttl, f"contract-{number}.pdf")))
        items.append(DownloadItem(beat_id=beat_id, license=row.License.code, contract_number=number, files=files))
    return Downloads(expires_at=datetime.now(UTC) + timedelta(seconds=ttl), items=items)


def purchases(db: Session, storage: ObjectStorage, user_id: int) -> Purchases:
    paid_at = paid_at_column().label("paid_at")
    rows = db.execute(
        select(OrderItem, Order, Beat.title, License.code, Contract.pdf_sha256, paid_at)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Beat, Beat.id == OrderItem.beat_id)
        .join(License, License.id == OrderItem.license_id)
        .outerjoin(Contract, Contract.order_item_id == OrderItem.id)
        .where(Order.customer_id == user_id, Order.status == "paid")
        .order_by(paid_at.desc().nulls_last(), OrderItem.order_id.desc(), OrderItem.id)
    ).all()
    # Item numbers inside each order: the contract number {order}-{n} (GAP-32)
    numbers: dict[int, list[int]] = {}
    for order_id, item_id in db.execute(
        select(OrderItem.order_id, OrderItem.id).where(OrderItem.order_id.in_({r.Order.id for r in rows})).order_by(OrderItem.id)
    ):
        numbers.setdefault(order_id, []).append(item_id)
    covers = dict(db.execute(select(BeatFile.beat_id, BeatFile.storage_key).where(
        BeatFile.beat_id.in_({r.OrderItem.beat_id for r in rows}), BeatFile.kind == "cover")).all())

    items = []
    for row in rows:
        item, order = row.OrderItem, row.Order
        cover = covers.get(item.beat_id)
        items.append(Purchase(
            order_id=order.id,
            item_id=item.id,
            contract_number=contract_number(order.id, numbers[order.id].index(item.id) + 1),
            beat_id=item.beat_id,
            title=row.title,
            cover_url=storage.public_url(cover) if cover and cover.startswith("covers/") else None,
            producer=order.billing_snapshot["licensors"].get(str(item.producer_id), {}).get("display_name", ""),
            license=row.code,
            price=item.price_at_purchase,
            service_fee=item.platform_fee,
            paid_at=row.paid_at,
            pdf_sha256=row.pdf_sha256,
        ))
    return Purchases(items=items)


MAX_PERIOD_DAYS = 366  # ASSUMPTION: GAP-69


def sales(db: Session, producer_id: int, date_from: date | None, date_to: date | None) -> Sales:
    """UC-14: the Producer's items of paid orders whose payment date falls into the period.
    ASSUMPTION: GAP-69 — dates are calendar days by Moscow time, both ends included; without
    parameters — the last 30 days."""
    today = datetime.now(MSK).date()
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise field_error("from", "period_reversed")
    if (date_to - date_from).days >= MAX_PERIOD_DAYS:
        raise field_error("from", "period_too_long", days=MAX_PERIOD_DAYS)
    start = datetime.combine(date_from, datetime.min.time(), MSK)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), MSK)

    paid_at = paid_at_column().label("paid_at")
    query = (
        select(OrderItem.order_id, OrderItem.beat_id, Beat.title, License.code, OrderItem.price_at_purchase, paid_at)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Beat, Beat.id == OrderItem.beat_id)
        .join(License, License.id == OrderItem.license_id)
        .where(OrderItem.producer_id == producer_id, Order.status == "paid")
    ).subquery()
    rows = db.execute(
        select(query).where(query.c.paid_at >= start, query.c.paid_at < end).order_by(query.c.paid_at.desc())
    ).all()
    items = [Sale(order_id=r.order_id, beat_id=r.beat_id, title=r.title, license=r.code,
                  price=r.price_at_purchase, paid_at=r.paid_at) for r in rows]
    return Sales(date_from=date_from, date_to=date_to, count=len(items),
                 total=sum((i.price for i in items), Decimal("0")), items=items)
