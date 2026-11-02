"""Bodies of /beats (REST API §2.1, §2.2, §2.4, §2.10)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.catalog.rules import (
    BPM_MAX,
    BPM_MIN,
    DESCRIPTION_MAX,
    GENRES_MAX,
    GENRES_MIN,
    LICENSE_CODES,
    MUSICAL_KEYS,
    PRICE_MAX,
    PRICE_MIN,
    TITLE_MAX,
    TITLE_MIN,
)
from app.common.validators import fail

# strict=True: "120" (string) and 120.5 are rejected, as in the UI spec ("blocks fractional values")
StrictPrice = Annotated[int, Field(strict=True, ge=PRICE_MIN, le=PRICE_MAX)]
LicenseCode = Literal["basic", "premium", "trackout", "exclusive"]
MusicalKey = Literal[tuple(MUSICAL_KEYS)]  # type: ignore[valid-type]


class LicenseIn(BaseModel):
    code: LicenseCode
    price: StrictPrice


class FileIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    size_bytes: Annotated[int, Field(strict=True, gt=0)]
    content_type: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=100)]


class FilesIn(BaseModel):
    wav: FileIn
    cover: FileIn
    stems: FileIn | None = None


class BeatCreate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=TITLE_MIN, max_length=TITLE_MAX)]
    genres: Annotated[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]],
                      Field(min_length=GENRES_MIN, max_length=GENRES_MAX)]
    bpm: Annotated[int, Field(strict=True, ge=BPM_MIN, le=BPM_MAX)]
    musical_key: MusicalKey
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=DESCRIPTION_MAX)] | None = None
    licenses: Annotated[list[LicenseIn], Field(min_length=1)]
    files: FilesIn

    @field_validator("genres")
    @classmethod
    def unique_genres(cls, value: list[str]) -> list[str]:
        if len({g.lower() for g in value}) != len(value):
            raise fail("duplicate_values")
        return value

    @field_validator("licenses")
    @classmethod
    def unique_licenses(cls, value: list[LicenseIn]) -> list[LicenseIn]:
        if len({lic.code for lic in value}) != len(value):
            raise fail("duplicate_values")
        return value

    @field_validator("description")
    @classmethod
    def empty_description_is_null(cls, value: str | None) -> str | None:
        return value or None


class UploadForm(BaseModel):
    url: str
    fields: dict[str, str]


class BeatCreated(BaseModel):
    id: int
    status: str
    upload_expires_at: datetime
    uploads: dict[str, UploadForm]


class UploadsRequest(BaseModel):
    files: Annotated[list[Literal["wav", "stems", "cover"]], Field(min_length=1, max_length=3)]


class UploadsOut(BaseModel):
    upload_expires_at: datetime
    uploads: dict[str, UploadForm]


class StatusOut(BaseModel):
    id: int
    status: str


class LicenseUpdate(BaseModel):
    price: StrictPrice
    is_active: bool = True


class StatusChange(BaseModel):
    status: Literal["hidden", "active"]


class LicenseOut(BaseModel):
    code: str
    price: int
    is_active: bool


class ProducerOut(BaseModel):
    id: int
    display_name: str


class BeatOut(BaseModel):
    """A beat card (REST API §2.3, §2.10). Owner-only fields are null for other users."""

    id: int
    title: str
    producer: ProducerOut
    genres: list[str]
    bpm: int
    musical_key: str
    description: str | None
    duration_sec: int | None
    cover_url: str | None
    preview_url: str | None
    is_reserved: bool
    licenses: list[LicenseOut]
    published_at: datetime | None
    # Owner only
    status: str | None = None
    rejection_reason: str | None = None
    created_at: datetime | None = None
    has_stems: bool | None = None


class BeatPage(BaseModel):
    items: list[BeatOut]
    next_cursor: str | None


LICENSE_CODE_LIST = list(LICENSE_CODES)
