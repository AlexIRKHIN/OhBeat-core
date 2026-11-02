"""HTTP layer of beats (REST API §2.1, §2.2, §2.4, §2.10)."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.catalog import service
from app.catalog.schemas import (
    BeatCreate,
    BeatCreated,
    BeatOut,
    BeatPage,
    LicenseUpdate,
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
