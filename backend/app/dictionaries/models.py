"""Reference tables: genres and licenses (Database_Schema.md §2.2)."""

from sqlalchemy import Boolean, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # basic | premium | trackout | exclusive
    name: Mapped[str] = mapped_column(String(64))
    includes_mp3: Mapped[bool] = mapped_column(Boolean)
    includes_wav: Mapped[bool] = mapped_column(Boolean)
    includes_stems: Mapped[bool] = mapped_column(Boolean)
    is_exclusive: Mapped[bool] = mapped_column(Boolean)
