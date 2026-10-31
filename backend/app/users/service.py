"""Profile, avatar, billing details and connecting to sales (FR-32, FR-33, REST API §2.9)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import get_roles
from app.common.audit import write_audit
from app.common.config import get_settings
from app.common.errors import ApiError, field_error
from app.common.i18n import t
from app.common.images import (
    EXTENSIONS_BY_CONTENT_TYPE,
    MAX_IMAGE_BYTES,
    ImageRejected,
    extension_of,
    inspect_image,
)
from app.common.storage import ObjectStorage, StorageUnavailable
from app.users.models import BillingProfile, ProducerAccount, Profile, User, UserRole
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


def _avatar_upload_prefix(user_id: int) -> str:
    return f"avatars/{user_id}/"


# --- Profile ---

def get_profile(db: Session, storage: ObjectStorage, user_id: int) -> ProfileOut:
    user = db.get(User, user_id)
    profile = db.get(Profile, user_id)
    if user is None or profile is None:
        raise ApiError(404, "NOT_FOUND")
    return ProfileOut(
        id=user.id,
        email=user.email,
        display_name=profile.display_name,
        bio=profile.bio,
        avatar_url=storage.public_url(profile.avatar_key) if profile.avatar_key else None,
        roles=sorted(get_roles(db, user_id)),
    )


def create_avatar_upload(storage: ObjectStorage, user_id: int, data: AvatarUploadRequest) -> UploadForm:
    """Presigned POST into temp-uploads, the same mechanism as for beat files (REST API §2.1, §2.9)."""
    if extension_of(data.name) not in EXTENSIONS_BY_CONTENT_TYPE[data.content_type]:
        raise field_error("name", "extension_mismatch")
    if data.size_bytes > MAX_IMAGE_BYTES:
        raise field_error("size_bytes", "file_too_large", max_mb=5)

    settings = get_settings()
    key = f"{_avatar_upload_prefix(user_id)}{uuid.uuid4().hex}.{extension_of(data.name)}"
    try:
        form = storage.presigned_post(
            settings.bucket_temp, key, data.content_type, MAX_IMAGE_BYTES, settings.presigned_ttl_seconds
        )
    except StorageUnavailable:
        raise ApiError(503, "STORAGE_UNAVAILABLE") from None
    return UploadForm(
        url=form.url,
        fields=form.fields,
        key=key,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.presigned_ttl_seconds),
    )


def _publish_avatar(storage: ObjectStorage, user_id: int, temp_key: str) -> str:
    """Check the uploaded file by content (NFR-22) and copy it to public-media."""
    settings = get_settings()
    # The key must be one we issued to this user, not someone else's file
    if not temp_key.startswith(_avatar_upload_prefix(user_id)):
        raise field_error("avatar_key", "file_not_uploaded")
    try:
        info = storage.head(settings.bucket_temp, temp_key)
        if info is None:
            raise field_error("avatar_key", "file_not_uploaded")
        if info.size_bytes > MAX_IMAGE_BYTES:
            raise field_error("avatar_key", "file_too_large", max_mb=5)
        data = storage.read(settings.bucket_temp, temp_key, MAX_IMAGE_BYTES)
        try:
            image = inspect_image(data)
        except ImageRejected as exc:
            raise field_error("avatar_key", exc.issue_key, max_mb=5) from None
        public_key = f"avatars/{user_id}_{uuid.uuid4().hex}.{image.extension}"
        # The name is unique, so the object never changes and may be cached for a year
        storage.put(
            settings.bucket_public, public_key, data, image.content_type,
            cache_control="public, max-age=31536000, immutable",
        )
    except StorageUnavailable:
        raise ApiError(503, "STORAGE_UNAVAILABLE") from None
    return public_key


def update_profile(db: Session, storage: ObjectStorage, user_id: int, data: ProfileUpdate) -> ProfileOut:
    profile = db.get(Profile, user_id)
    if profile is None:
        raise ApiError(404, "NOT_FOUND")
    profile.display_name = data.display_name
    profile.bio = data.bio or None
    # avatar_key absent from the body: keep the avatar; null: remove it; a key: publish the new file
    if "avatar_key" in data.model_fields_set:
        if data.avatar_key is None:
            profile.avatar_key = None
        else:
            profile.avatar_key = _publish_avatar(storage, user_id, data.avatar_key)
    db.commit()
    return get_profile(db, storage, user_id)


# --- Billing details ---

def _billing_out(row: BillingProfile) -> BillingOut:
    return BillingOut.model_validate(row, from_attributes=True)


def get_billing(db: Session, user_id: int) -> BillingOut:
    row = db.get(BillingProfile, user_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND")
    return _billing_out(row)


def put_billing(db: Session, user_id: int, data: BillingIn) -> BillingOut:
    missing = data.missing_business_fields()
    if missing:
        raise ApiError(
            400, "VALIDATION_ERROR", [{"field": f, "issue": t("business_field_required")} for f in missing]
        )
    row = db.get(BillingProfile, user_id) or BillingProfile(user_id=user_id)
    for field, value in data.model_dump().items():
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    db.add(row)
    db.commit()
    return _billing_out(row)


# --- Connecting to sales ---

def connect_producer(db: Session, user_id: int, data: ProducerAccountIn, ip: str | None) -> ProducerAccountOut:
    """FR-33: billing details must exist; the role and the account appear in one transaction."""
    if db.scalar(select(UserRole).where(UserRole.user_id == user_id, UserRole.role == "producer")):
        raise ApiError(409, "ALREADY_PRODUCER")
    if db.get(BillingProfile, user_id) is None:
        raise ApiError(409, "BILLING_REQUIRED")

    now = datetime.now(UTC)
    account = ProducerAccount(
        user_id=user_id,
        tax_status=data.tax_status,
        yookassa_account_id=data.yookassa_account_id,
        pep_agreement_at=now,
    )
    db.add(account)
    db.add(UserRole(user_id=user_id, role="producer"))
    write_audit(
        db, action="producer.connected", entity="user", entity_id=user_id, actor_user_id=user_id, ip=ip,
        details={
            "tax_status": data.tax_status,
            "pep_agreement_accepted": True,
            "license_terms_accepted": True,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        # Two simultaneous requests: the second hits the primary key of producer_accounts
        db.rollback()
        raise ApiError(409, "ALREADY_PRODUCER") from None
    return ProducerAccountOut(
        tax_status=account.tax_status,
        yookassa_account_id=account.yookassa_account_id,
        pep_agreement_at=account.pep_agreement_at,
        roles=sorted(get_roles(db, user_id)),
    )
