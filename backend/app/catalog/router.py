"""HTTP layer of beats (REST API §2.1, §2.2, §2.4, §2.10)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.catalog import service
from app.catalog.browse import CatalogFilters, browse, producer_page
from app.catalog.rules import BPM_MAX, BPM_MIN
from app.catalog.schemas import (
    BeatCreate,
    BeatCreated,
    BeatOut,
    BeatPage,
    LicenseUpdate,
    MusicalKey,
    ProducerPage,
    StatusChange,
    StatusOut,
    UploadsOut,
    UploadsRequest,
)
from app.common.auth_deps import CurrentUser, get_optional_user, require_role
from app.common.db import get_db
from app.common.storage import ObjectStorage, get_storage

router = APIRouter(tags=["beats"])
producer_only = require_role("producer")


def catalog_filters(
    genre: str | None = Query(None, max_length=64),
    bpm_min: int | None = Query(None, ge=BPM_MIN, le=BPM_MAX),
    bpm_max: int | None = Query(None, ge=BPM_MIN, le=BPM_MAX),
    musical_key: MusicalKey | None = Query(None),
    price_max: int | None = Query(None, ge=0),
    sort: Literal["newest"] = Query("newest"),  # ASSUMPTION: GAP-24 — the only documented order
) -> CatalogFilters:
    return CatalogFilters(genre=genre, bpm_min=bpm_min, bpm_max=bpm_max, musical_key=musical_key, price_max=price_max)


# ASSUMPTION: GAP-60 — 20 by default (the example of REST API §2.3), at most 50
PageSize = Query(20, ge=1, le=50)


@router.get("/beats", response_model=BeatPage)
def catalog(
    filters: CatalogFilters = Depends(catalog_filters),
    cursor: str | None = Query(None, max_length=200),
    limit: int = PageSize,
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> BeatPage:
    """REST API §2.3. Public. Beats in `active` and `reserved` (with is_reserved), newest first,
    prices of the Producer without the service fee. Errors: 400 VALIDATION_ERROR."""
    return browse(db, storage, filters, cursor, limit)


@router.get("/producers/{producer_id}", response_model=ProducerPage)
def producer(
    producer_id: int,
    filters: CatalogFilters = Depends(catalog_filters),
    cursor: str | None = Query(None, max_length=200),
    limit: int = PageSize,
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ProducerPage:
    """REST API §2.9. Public profile and showcase with the catalog filters. Errors: 404 NOT_FOUND."""
    return producer_page(db, storage, producer_id, filters, cursor, limit)


@router.post("/beats", status_code=status.HTTP_201_CREATED, response_model=BeatCreated)
def create_beat(
    data: BeatCreate,
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> BeatCreated:
    """FR-6. Creates a beat in `uploading` and returns a presigned POST form for every file.
    Errors: 400 VALIDATION_ERROR (incl. stop-list), 403 FORBIDDEN (no Producer role)."""
    return service.create_beat(db, storage, user.id, data)


@router.post("/beats/{beat_id}/uploads", response_model=UploadsOut)
def reissue_uploads(
    beat_id: int,
    data: UploadsRequest,
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadsOut:
    """FR-6. New forms instead of expired ones. Errors: 403, 409 INVALID_STATUS."""
    return service.reissue_uploads(db, storage, user.id, beat_id, data)


@router.post("/beats/{beat_id}/confirm", status_code=status.HTTP_202_ACCEPTED, response_model=StatusOut)
def confirm_upload(
    beat_id: int,
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> StatusOut:
    """FR-7. HeadObject for every file, then `processing` + outbox event in one transaction.
    Errors: 409 INVALID_STATUS, 422 FILES_MISSING."""
    return service.confirm_upload(db, storage, user.id, beat_id)


@router.get("/beats/{beat_id}", response_model=BeatOut, response_model_exclude_none=False)
def get_beat(
    beat_id: int,
    viewer: CurrentUser | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> BeatOut:
    """Public for active and reserved beats; the owner sees any status except deleted."""
    return service.get_beat(db, storage, beat_id, viewer)


@router.get("/users/me/beats", response_model=BeatPage)
def my_beats(
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> BeatPage:
    """FR-34 "My beats": all statuses except deleted, with the rejection reason."""
    return service.list_my_beats(db, storage, user.id, cursor, limit)


@router.put("/beats/{beat_id}/licenses/{code}", response_model=BeatOut)
def update_license(
    beat_id: int,
    code: str,
    data: LicenseUpdate,
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> BeatOut:
    """Errors: 403, 404, 409 BEAT_SOLD, LAST_ACTIVE_LICENSE, STEMS_REQUIRED."""
    return service.update_license(db, storage, user.id, beat_id, code, data)


@router.patch("/beats/{beat_id}", response_model=BeatOut)
def change_status(
    beat_id: int,
    data: StatusChange,
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> BeatOut:
    """Hide or return to sale. Errors: 403, 409 BEAT_RESERVED, BEAT_SOLD, INVALID_STATUS."""
    return service.change_status(db, storage, user.id, beat_id, data)


@router.delete("/beats/{beat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_beat(
    beat_id: int,
    user: CurrentUser = Depends(producer_only),
    db: Session = Depends(get_db),
) -> Response:
    """Logical deletion (NFR-20). Errors: 403, 409 BEAT_RESERVED, BEAT_SOLD."""
    service.delete_beat(db, user.id, beat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
