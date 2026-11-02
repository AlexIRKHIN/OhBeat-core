"""Cart (FR-14, FR-15, FR-19, REST API §2.11). Kept on the server in `cart_items`."""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import Beat, BeatFile, BeatPrice
from app.catalog.rules import LICENSE_CODES
from app.common.config import get_settings
from app.common.errors import ApiError
from app.common.storage import ObjectStorage
from app.dictionaries.models import License
from app.orders.models import CartItem
from app.orders.money import service_fee
from app.orders.schemas import CartItemOut, CartOut
from app.users.models import Profile


def unavailable_reason(beat: Beat | None, price: BeatPrice | None, buyer_id: int) -> str | None:
    """Why a beat cannot be bought right now (FR-14, FR-19). None means it can."""
    if beat is None or beat.status == "deleted":
        return "BEAT_NOT_AVAILABLE"
    if beat.producer_id == buyer_id:
        return "OWN_BEAT"  # ASSUMPTION: GAP-26
    if beat.status == "reserved":
        return "BEAT_RESERVED"  # FR-19: no license of a reserved beat
    if beat.status == "sold":
        return "BEAT_SOLD"
    if beat.status != "active":
        return "BEAT_NOT_AVAILABLE"  # hidden, processing...
    if price is None or not price.is_active:
        return "LICENSE_INACTIVE"
    return None


def get_cart(db: Session, storage: ObjectStorage, user_id: int) -> CartOut:
    rows = db.execute(
        select(CartItem, Beat, License, BeatPrice)
        .join(Beat, Beat.id == CartItem.beat_id)
        .join(License, License.id == CartItem.license_id)
        .outerjoin(BeatPrice, (BeatPrice.beat_id == CartItem.beat_id) & (BeatPrice.license_id == CartItem.license_id))
        .where(CartItem.user_id == user_id, Beat.status != "deleted")
        .order_by(CartItem.added_at)
    ).all()
    covers = dict(db.execute(
        select(BeatFile.beat_id, BeatFile.storage_key)
        .where(BeatFile.beat_id.in_([r.Beat.id for r in rows]), BeatFile.kind == "cover")
    ).all())
    names = dict(db.execute(
        select(Profile.user_id, Profile.display_name).where(Profile.user_id.in_({r.Beat.producer_id for r in rows}))
    ).all())

    items, items_total, fee_total = [], Decimal("0"), Decimal("0")
    for row in rows:
        reason = unavailable_reason(row.Beat, row.BeatPrice, user_id)
        price = Decimal(row.BeatPrice.price) if row.BeatPrice else Decimal("0")
        fee = service_fee(price)
        cover = covers.get(row.Beat.id)
        items.append(CartItemOut(
            beat_id=row.Beat.id,
            title=row.Beat.title,
            producer=names.get(row.Beat.producer_id, ""),
            cover_url=storage.public_url(cover) if cover and cover.startswith("covers/") else None,
            license=row.License.code,
            price=price,
            service_fee=fee,
            available=reason is None,
            unavailable_reason=reason,
        ))
        if reason is None:  # FR-15: totals count only what can be bought
            items_total += price
            fee_total += fee
    return CartOut(
        items=items,
        items_total=items_total,
        service_fee=fee_total,
        total=items_total + fee_total,
        fee_percent=get_settings().platform_fee_percent,
    )


def put_item(db: Session, storage: ObjectStorage, user_id: int, beat_id: int, license_code: str) -> CartOut:
    """FR-14: one beat — one license; choosing another license replaces the previous one."""
    if license_code not in LICENSE_CODES:
        raise ApiError(404, "NOT_FOUND")
    beat = db.get(Beat, beat_id)
    if beat is None or beat.status in ("uploading", "deleted"):
        raise ApiError(404, "NOT_FOUND")
    license_row = db.scalar(select(License).where(License.code == license_code))
    price = db.get(BeatPrice, (beat_id, license_row.id))
    reason = unavailable_reason(beat, price, user_id)
    if reason:
        raise ApiError(409, reason)

    db.execute(
        insert(CartItem)
        .values(user_id=user_id, beat_id=beat_id, license_id=license_row.id)
        .on_conflict_do_update(index_elements=["user_id", "beat_id"], set_={"license_id": license_row.id})
    )
    db.commit()
    return get_cart(db, storage, user_id)


def remove_item(db: Session, user_id: int, beat_id: int) -> None:
    db.execute(delete(CartItem).where(CartItem.user_id == user_id, CartItem.beat_id == beat_id))
    db.commit()
