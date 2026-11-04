"""Bodies of downloads, "My purchases" and sales statistics (REST API §2.6, §2.10, §2.12)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.orders.schemas import Money


class DownloadFile(BaseModel):
    kind: Literal["mp3", "wav", "stems", "contract"]
    url: str


class DownloadItem(BaseModel):
    beat_id: int
    license: str
    contract_number: str
    files: list[DownloadFile]


class Downloads(BaseModel):
    expires_at: datetime
    items: list[DownloadItem]


class Purchase(Money):
    order_id: int
    item_id: int
    contract_number: str
    beat_id: int
    title: str
    cover_url: str | None
    producer: str
    license: str
    price: Decimal
    service_fee: Decimal
    paid_at: datetime | None
    pdf_sha256: str | None


class Purchases(BaseModel):
    items: list[Purchase]


class Sale(Money):
    order_id: int
    beat_id: int
    title: str
    license: str
    price: Decimal  # the Producer's price, without the service fee
    paid_at: datetime


class Sales(Money):
    date_from: date
    date_to: date
    count: int
    total: Decimal
    items: list[Sale]
