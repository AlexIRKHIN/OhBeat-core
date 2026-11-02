"""GET /dictionaries — public reference data for forms (ASSUMPTION: GAP-15)."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.rules import LICENSE_CODES, MUSICAL_KEYS
from app.common.config import get_settings
from app.common.db import get_db
from app.dictionaries.models import Genre, License

router = APIRouter(tags=["dictionaries"])

LICENSE_ORDER = list(LICENSE_CODES)


class GenreOut(BaseModel):
    id: int
    name: str


class LicenseOut(BaseModel):
    code: str
    name: str
    includes_mp3: bool
    includes_wav: bool
    includes_stems: bool
    is_exclusive: bool


class DictionariesOut(BaseModel):
    genres: list[GenreOut]
    musical_keys: list[str]
    licenses: list[LicenseOut]
    platform_fee_percent: Decimal


@router.get("/dictionaries", response_model=DictionariesOut)
def get_dictionaries(db: Session = Depends(get_db)) -> DictionariesOut:
    genres = db.scalars(select(Genre).order_by(Genre.name))
    licenses = sorted(db.scalars(select(License)), key=lambda lic: LICENSE_ORDER.index(lic.code))
    return DictionariesOut(
        genres=[GenreOut(id=g.id, name=g.name) for g in genres],
        musical_keys=MUSICAL_KEYS,
        licenses=[LicenseOut.model_validate(lic, from_attributes=True) for lic in licenses],
        platform_fee_percent=get_settings().platform_fee_percent,
    )
