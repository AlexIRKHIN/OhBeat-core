"""HTTP layer of /users/me (REST API §2.9). Every endpoint works only with the caller's own data."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.common.auth_deps import CurrentUser, client_ip, get_current_user
from app.common.db import get_db
from app.common.storage import ObjectStorage, get_storage
from app.users import service
from app.users.schemas import (
    AvatarUploadRequest,
    BillingIn,
    BillingOut,
    ProducerAccountIn,
    ProducerAccountOut,
    ProfileOut,
    ProfileUpdate,
    UploadForm,
)

router = APIRouter(prefix="/users/me", tags=["users"])


@router.get("", response_model=ProfileOut)
def get_me(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ProfileOut:
    return service.get_profile(db, storage, user.id)


@router.put("", response_model=ProfileOut)
def put_me(
    data: ProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ProfileOut:
    """FR-32. A new avatar_key is checked by content and moved to public-media."""
    return service.update_profile(db, storage, user.id, data)


@router.post("/avatar", response_model=UploadForm)
def avatar_upload_form(
    data: AvatarUploadRequest,
    user: CurrentUser = Depends(get_current_user),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadForm:
    return service.create_avatar_upload(storage, user.id, data)


@router.get("/billing", response_model=BillingOut)
def get_billing(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> BillingOut:
    """404 NOT_FOUND while the form has never been saved."""
    return service.get_billing(db, user.id)


@router.put("/billing", response_model=BillingOut)
def put_billing(
    data: BillingIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> BillingOut:
    return service.put_billing(db, user.id, data)


@router.post("/producer-account", status_code=status.HTTP_201_CREATED, response_model=ProducerAccountOut)
def connect_producer(
    data: ProducerAccountIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProducerAccountOut:
    """FR-33. Errors: 409 ALREADY_PRODUCER, 409 BILLING_REQUIRED."""
    return service.connect_producer(db, user.id, data, client_ip(request))
