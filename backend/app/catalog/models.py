"""Tables of the "Catalog" area (Database_Schema.md §2.2). Column types follow schema.sql."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Beat(Base):
    __tablename__ = "beats"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    producer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(60))
    bpm: Mapped[int] = mapped_column(SmallInteger)
    musical_key: Mapped[str] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    # uploading | processing | active | reserved | sold | rejected | hidden | deleted
    status: Mapped[str] = mapped_column(String(32))
    reserved_order_id: Mapped[int | None] = mapped_column(BigInteger)
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class BeatFile(Base):
    """While the beat is `uploading`, rows hold temporary keys and declared sizes (ASSUMPTION: GAP-53)."""

    __tablename__ = "beat_files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    beat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("beats.id"))
    kind: Mapped[str] = mapped_column(String(32))  # cover | master | stems | clean_mp3 | preview_mp3
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))


class BeatGenre(Base):
    __tablename__ = "beat_genres"

    beat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("beats.id"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(Integer, ForeignKey("genres.id"), primary_key=True)


class BeatPrice(Base):
    __tablename__ = "beat_prices"

    beat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("beats.id"), primary_key=True)
    license_id: Mapped[int] = mapped_column(Integer, ForeignKey("licenses.id"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class StopWord(Base):
    __tablename__ = "stop_words"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    word: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
