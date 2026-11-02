"""Bodies of /cart and /orders (REST API §2.5, §2.6, §2.11)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_serializer, field_validator

from app.common.validators import check_true, fail

LicenseCode = Literal["basic", "premium", "trackout", "exclusive"]


class Money(BaseModel):
    """Amounts are sent as numbers with kopecks (e.g. 4950.0, 450.5)."""

    @field_serializer("*", when_used="json", check_fields=False)
    def _decimal_as_number(self, value):
        return float(value) if isinstance(value, Decimal) else value


# --- Cart ---

class CartPut(BaseModel):
    license: LicenseCode


class CartItemOut(Money):
    beat_id: int
    title: str
    producer: str
    cover_url: str | None
    license: str
    price: Decimal
    service_fee: Decimal
    available: bool
    # BEAT_RESERVED | BEAT_SOLD | BEAT_NOT_AVAILABLE | LICENSE_INACTIVE | OWN_BEAT | IN_YOUR_ORDER (GAP-66)
    unavailable_reason: str | None
    order_id: int | None = None  # IN_YOUR_ORDER: the pending order of this buyer that holds the reservation


class CartOut(Money):
    items: list[CartItemOut]
    items_total: Decimal
    service_fee: Decimal
    total: Decimal
    fee_percent: Decimal


# --- Orders ---

class OrderItemIn(BaseModel):
    beat_id: int
    license: LicenseCode
    # FR-15: the price the Artist saw; a different current price -> 409 PRICE_CHANGED
    expected_price: Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class OrderCreate(BaseModel):
    items: Annotated[list[OrderItemIn], Field(min_length=1, max_length=20)]
    offer_accepted: Annotated[bool, AfterValidator(check_true)]  # FR-16, ASSUMPTION: GAP-28 — always required

    @field_validator("items")
    @classmethod
    def one_line_per_beat(cls, items: list[OrderItemIn]) -> list[OrderItemIn]:
        # order_items UNIQUE (order_id, beat_id): one beat — one line
        if len({i.beat_id for i in items}) != len(items):
            raise fail("duplicate_values")
        return items


class OrderCreated(Money):
    order_id: int
    status: str
    items_total: Decimal
    service_fee: Decimal
    total: Decimal
    requires_signature: bool
    reserved_until: datetime | None


class OrderItemOut(Money):
    item_id: int
    contract_number: str
    beat_id: int
    title: str
    cover_url: str | None
    producer: str
    license: str
    price: Decimal
    service_fee: Decimal


class OrderOut(Money):
    """ASSUMPTION: GAP-63 — wider than {order_id, status} of REST API §2.6: the pages need the details."""

    order_id: int
    status: str
    created_at: datetime
    items_total: Decimal
    service_fee: Decimal
    total: Decimal
    items: list[OrderItemOut]
    requires_signature: bool
    signed: bool
    reserved_until: datetime | None
    payment_status: str | None
    payment_cancel_reason: str | None = None  # e.g. insufficient_funds — the bank declined (FR-25)
    cancel_reason: str | None = None  # why the order was canceled at the FR-23 check (BEAT_SOLD, …)
