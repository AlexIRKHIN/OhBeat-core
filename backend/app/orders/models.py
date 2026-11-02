"""Tables of carts, orders, payments and contracts (Database_Schema.md §2.3). Types follow schema.sql."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Identity, Integer, Numeric, SmallInteger, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class CartItem(Base):
    __tablename__ = "cart_items"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    beat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("beats.id"), primary_key=True)
    license_id: Mapped[int] = mapped_column(Integer, ForeignKey("licenses.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32))  # pending | paid | expired | canceled
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # {"buyer": {...}, "licensors": {"<producer_id>": {...}}} — ASSUMPTION: GAP-8
    billing_snapshot: Mapped[dict] = mapped_column(JSONB)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"))
    beat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("beats.id"))
    license_id: Mapped[int] = mapped_column(Integer, ForeignKey("licenses.id"))
    producer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    price_at_purchase: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # the Producer's price (FR-18)
    platform_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # the service fee on top (FR-30)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"))
    provider_payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    idempotence_key: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    status: Mapped[str] = mapped_column(String(32))  # pending | waiting_for_capture | succeeded | canceled
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider_payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.provider_payment_id"))
    event: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    """One contract per order item (RFC ПЭП §6; UNIQUE (order_item_id) — GAP-2)."""

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("order_items.id"), unique=True)
    signature_type: Mapped[str] = mapped_column(String(32))  # offer_accept | otp
    draft_sha256: Mapped[str] = mapped_column(CHAR(64))
    pdf_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    pdf_key: Mapped[str | None] = mapped_column(String(512))
    signer_ip: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signer_phone: Mapped[str | None] = mapped_column(String(32))


class SignatureOtp(Base):
    __tablename__ = "signature_otps"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"))
    code_hash: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
