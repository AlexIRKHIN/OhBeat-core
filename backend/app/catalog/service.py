"""Beats of a Producer: creation, upload confirmation, "My beats", prices and statuses.

FR-6, FR-7, FR-13, FR-34; REST API §2.1, §2.2, §2.4, §2.10.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.catalog.models import Beat, BeatFile, BeatGenre, BeatPrice
from app.catalog.rules import FIELD_BY_KIND, FILE_RULES, IMAGE_EXTENSIONS, LICENSE_CODES, LICENSES_NEEDING_STEMS, MB
from app.catalog.schemas import (
    BeatCreate,
    BeatCreated,
    BeatOut,
    BeatPage,
    FileIn,
    LicenseOut,
    LicenseUpdate,
    ProducerOut,
    StatusChange,
    StatusOut,
    UploadForm,
    UploadsOut,
    UploadsRequest,
)
from app.catalog.stoplist import contains_stop_word, load_stop_words
from app.common.auth_deps import CurrentUser
from app.common.config import get_settings
from app.common.errors import ApiError
from app.common.i18n import t
from app.common.images import extension_of
from app.common.outbox import add_event
from app.common.rabbit import PROCESS_KEY
from app.common.storage import ObjectStorage, StorageUnavailable
from app.dictionaries.models import Genre, License
from app.users.models import Profile

PUBLIC_STATUSES = ("active", "reserved")  # REST API §2.3: what the catalog shows


def _detail(field: str, issue_key: str, **params: object) -> dict:
    return {"field": field, "issue": t(issue_key, **params)}


# --- Creating a beat (FR-6) ---

def _check_file(field: str, file: FileIn) -> tuple[list[dict], str, str]:
    """Declared extension, MIME type and size. Returns (errors, canonical content type, stored extension)."""
    rule = FILE_RULES[field]
    errors = []
    ext = extension_of(file.name)
    if ext not in rule.extensions:
        errors.append(_detail(f"files.{field}.name", "file_extension_not_allowed"))
    content_type = rule.content_types.get(file.content_type)
    if content_type is None:
        errors.append(_detail(f"files.{field}.content_type", "file_type_not_allowed_for"))
    elif field == "cover" and ext not in IMAGE_EXTENSIONS[content_type]:
        errors.append(_detail(f"files.{field}.name", "extension_mismatch"))
    if file.size_bytes > rule.max_bytes:
        errors.append(_detail(f"files.{field}.size_bytes", "file_too_large", max_mb=rule.max_bytes // MB))
    return errors, content_type or "", rule.extensions.get(ext, "")


def _raw_key(beat_id: int, field: str, ext: str) -> str:
    name = {"wav": "master", "stems": "stems", "cover": "cover"}[field]
    return f"raw/{beat_id}/{name}.{ext}"


def _upload_form(storage: ObjectStorage, key: str, field: str, content_type: str) -> UploadForm:
    settings = get_settings()
    try:
        form = storage.presigned_post(
            settings.bucket_temp, key, content_type, FILE_RULES[field].max_bytes, settings.presigned_ttl_seconds
        )
    except StorageUnavailable:
        raise ApiError(503, "STORAGE_UNAVAILABLE") from None
    return UploadForm(url=form.url, fields=form.fields)


def _expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=get_settings().presigned_ttl_seconds)


def create_beat(db: Session, storage: ObjectStorage, user_id: int, data: BeatCreate) -> BeatCreated:
    errors: list[dict] = []

    # Stop-list (FR-6)
    stop_words = load_stop_words(db)
    if contains_stop_word(data.title, stop_words):
        errors.append(_detail("title", "forbidden_word"))
    if data.description and contains_stop_word(data.description, stop_words):
        errors.append(_detail("description", "forbidden_word"))

    # Genres must exist in the dictionary (case-insensitive match, stored name is used)
    genres_by_name = {g.name.lower(): g for g in db.scalars(select(Genre))}
    genres = []
    for i, name in enumerate(data.genres):
        genre = genres_by_name.get(name.lower())
        if genre is None:
            errors.append(_detail(f"genres[{i}]", "unknown_genre"))
        else:
            genres.append(genre)

    # Declared files (FR-6); stems are required for Trackout / Exclusive (FR-1)
    declared = {"wav": data.files.wav, "cover": data.files.cover}
    if data.files.stems is not None:
        declared["stems"] = data.files.stems
    elif LICENSES_NEEDING_STEMS & {lic.code for lic in data.licenses}:
        errors.append(_detail("files.stems", "stems_required"))
    checked = {}
    for field, file in declared.items():
        file_errors, content_type, ext = _check_file(field, file)
        errors += file_errors
        checked[field] = (file, content_type, ext)

    if errors:
        raise ApiError(400, "VALIDATION_ERROR", errors)

    beat = Beat(
        producer_id=user_id,
        title=data.title,
        bpm=data.bpm,
        musical_key=data.musical_key,
        description=data.description,
        status="uploading",
    )
    db.add(beat)
    db.flush()  # beat.id is needed for the object keys

    db.add_all(BeatGenre(beat_id=beat.id, genre_id=g.id) for g in genres)
    licenses = {lic.code: lic.id for lic in db.scalars(select(License))}
    db.add_all(
        BeatPrice(beat_id=beat.id, license_id=licenses[lic.code], price=Decimal(lic.price), is_active=True)
        for lic in data.licenses
    )

    uploads = {}
    for field, (file, content_type, ext) in checked.items():
        key = _raw_key(beat.id, field, ext)
        # ASSUMPTION: GAP-53 — the row remembers the declared file until processing replaces the key
        db.add(BeatFile(beat_id=beat.id, kind=FILE_RULES[field].kind, storage_key=key, size_bytes=file.size_bytes))
        uploads[field] = _upload_form(storage, key, field, content_type)

    db.commit()
    return BeatCreated(id=beat.id, status=beat.status, upload_expires_at=_expires_at(), uploads=uploads)


# --- Owner access ---

def _owned_beat(db: Session, beat_id: int, user_id: int, lock: bool = True) -> Beat:
    """404 for a missing or deleted beat, 403 for someone else's. Locks the row for the transaction."""
    query = select(Beat).where(Beat.id == beat_id)
    if lock:
        query = query.with_for_update()
    beat = db.scalar(query)
    if beat is None or beat.status == "deleted":
        raise ApiError(404, "NOT_FOUND")
    if beat.producer_id != user_id:
        raise ApiError(403, "FORBIDDEN")
    return beat


def _files_of(db: Session, beat_id: int) -> dict[str, BeatFile]:
    return {f.kind: f for f in db.scalars(select(BeatFile).where(BeatFile.beat_id == beat_id))}


# --- New upload forms instead of expired ones (FR-6, REST API §2.10) ---

def reissue_uploads(db: Session, storage: ObjectStorage, user_id: int, beat_id: int, data: UploadsRequest) -> UploadsOut:
    beat = _owned_beat(db, beat_id, user_id, lock=False)
    if beat.status != "uploading":
        raise ApiError(409, "INVALID_STATUS")
    files = _files_of(db, beat_id)
    uploads, errors = {}, []
    for field in dict.fromkeys(data.files):  # keeps order, drops repeats
        row = files.get(FILE_RULES[field].kind)
        if row is None:
            errors.append(_detail("files", "file_not_declared"))
            continue
        ext = row.storage_key.rsplit(".", 1)[-1]
        content_type = next(iter(FILE_RULES[field].content_types.values()))
        if field == "cover":
            content_type = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext]
        uploads[field] = _upload_form(storage, row.storage_key, field, content_type)
    if errors:
        raise ApiError(400, "VALIDATION_ERROR", errors)
    return UploadsOut(upload_expires_at=_expires_at(), uploads=uploads)


# --- Upload confirmation (FR-7) ---

def confirm_upload(db: Session, storage: ObjectStorage, user_id: int, beat_id: int) -> StatusOut:
    settings = get_settings()
    beat = _owned_beat(db, beat_id, user_id)  # row lock: two parallel confirms cannot both pass
    if beat.status != "uploading":
        raise ApiError(409, "INVALID_STATUS")

    files = _files_of(db, beat_id)
    problems = []
    for kind, row in files.items():
        field = FIELD_BY_KIND[kind]
        try:
            info = storage.head(settings.bucket_temp, row.storage_key)  # HeadObject: presence and real size
        except StorageUnavailable:
            raise ApiError(503, "STORAGE_UNAVAILABLE") from None
        if info is None:
            problems.append(_detail(f"files.{field}", "file_not_uploaded"))
        elif info.size_bytes > FILE_RULES[field].max_bytes:
            problems.append(_detail(f"files.{field}", "file_too_large", max_mb=FILE_RULES[field].max_bytes // MB))
        else:
            row.size_bytes = info.size_bytes
    if problems:
        db.rollback()
        raise ApiError(422, "FILES_MISSING", problems)

    # One transaction: the new status and the event for Media Worker (transactional outbox)
    beat.status = "processing"
    add_event(
        db,
        PROCESS_KEY,
        {
            "beat_id": beat.id,
            "producer_id": beat.producer_id,
            "files": {
                "wav_key": files["master"].storage_key,
                "stems_key": files["stems"].storage_key if "stems" in files else None,
                "cover_key": files["cover"].storage_key,
            },
            "options": {"voice_tag": True, "tag_interval_sec": settings.voice_tag_interval_sec},
        },
    )
    db.commit()
    return StatusOut(id=beat.id, status=beat.status)


# --- Cards ---

def _public_url(storage: ObjectStorage, row: BeatFile | None, prefix: str) -> str | None:
    # Until processing ends the key points to temp-uploads, which is not public
    if row is None or not row.storage_key.startswith(prefix):
        return None
    return storage.public_url(row.storage_key)


def build_cards(db: Session, storage: ObjectStorage, beats: list[Beat], owner_view: bool) -> list[BeatOut]:
    if not beats:
        return []
    ids = [b.id for b in beats]
    genres: dict[int, list[str]] = {}
    for beat_id, name in db.execute(
        select(BeatGenre.beat_id, Genre.name).join(Genre, Genre.id == BeatGenre.genre_id)
        .where(BeatGenre.beat_id.in_(ids)).order_by(Genre.name)
    ):
        genres.setdefault(beat_id, []).append(name)

    prices: dict[int, list[LicenseOut]] = {}
    for beat_id, code, price, active in db.execute(
        select(BeatPrice.beat_id, License.code, BeatPrice.price, BeatPrice.is_active)
        .join(License, License.id == BeatPrice.license_id).where(BeatPrice.beat_id.in_(ids))
    ):
        if active or owner_view:
            prices.setdefault(beat_id, []).append(LicenseOut(code=code, price=int(price), is_active=active))
    for items in prices.values():
        items.sort(key=lambda lic: LICENSE_CODES.index(lic.code))

    files: dict[int, dict[str, BeatFile]] = {}
    for row in db.scalars(select(BeatFile).where(BeatFile.beat_id.in_(ids))):
        files.setdefault(row.beat_id, {})[row.kind] = row

    names = dict(db.execute(select(Profile.user_id, Profile.display_name).where(
        Profile.user_id.in_({b.producer_id for b in beats}))).all())

    cards = []
    for b in beats:
        f = files.get(b.id, {})
        card = BeatOut(
            id=b.id,
            title=b.title,
            producer=ProducerOut(id=b.producer_id, display_name=names.get(b.producer_id, "")),
            genres=genres.get(b.id, []),
            bpm=b.bpm,
            musical_key=b.musical_key,
            description=b.description,
            duration_sec=b.duration_sec,
            cover_url=_public_url(storage, f.get("cover"), "covers/"),
            preview_url=_public_url(storage, f.get("preview_mp3"), "previews/"),
            is_reserved=b.status == "reserved",
            licenses=prices.get(b.id, []),
            published_at=b.published_at,
        )
        if owner_view:
            card.status = b.status
            card.rejection_reason = b.rejection_reason
            card.created_at = b.created_at
            card.has_stems = "stems" in f
        cards.append(card)
    return cards


def get_beat(db: Session, storage: ObjectStorage, beat_id: int, viewer: CurrentUser | None) -> BeatOut:
    """REST API §2.10: public — active and reserved; the owner — any status except deleted."""
    beat = db.get(Beat, beat_id)
    if beat is None or beat.status == "deleted":
        raise ApiError(404, "NOT_FOUND")
    is_owner = viewer is not None and viewer.id == beat.producer_id
    if not is_owner and beat.status not in PUBLIC_STATUSES:
        raise ApiError(404, "NOT_FOUND")
    return build_cards(db, storage, [beat], owner_view=is_owner)[0]


# --- "My beats" (FR-34) ---

def _encode_cursor(beat_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"id": beat_id}).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return int(json.loads(base64.urlsafe_b64decode(padded))["id"])
    except (ValueError, KeyError, TypeError):
        raise ApiError(400, "VALIDATION_ERROR", [_detail("cursor", "invalid_value")]) from None


def list_my_beats(db: Session, storage: ObjectStorage, user_id: int, cursor: str | None, limit: int) -> BeatPage:
    """All statuses except deleted, newest first. Cursor = id of the last beat on the previous page."""
    query = select(Beat).where(Beat.producer_id == user_id, Beat.status != "deleted")
    after = _decode_cursor(cursor)
    if after is not None:
        query = query.where(Beat.id < after)
    beats = list(db.scalars(query.order_by(Beat.id.desc()).limit(limit + 1)))
    next_cursor = _encode_cursor(beats[limit - 1].id) if len(beats) > limit else None
    return BeatPage(items=build_cards(db, storage, beats[:limit], owner_view=True), next_cursor=next_cursor)


# --- Prices (REST API §2.4) ---

def update_license(
    db: Session, storage: ObjectStorage, user_id: int, beat_id: int, code: str, data: LicenseUpdate
) -> BeatOut:
    license_row = db.scalar(select(License).where(License.code == code))
    if license_row is None:
        raise ApiError(404, "NOT_FOUND")
    beat = _owned_beat(db, beat_id, user_id)
    if beat.status == "sold":
        raise ApiError(409, "BEAT_SOLD")

    if data.is_active and code in LICENSES_NEEDING_STEMS and "stems" not in _files_of(db, beat_id):
        raise ApiError(409, "STEMS_REQUIRED")

    price = db.get(BeatPrice, (beat_id, license_row.id))
    if not data.is_active:
        active = db.scalars(
            select(BeatPrice.license_id).where(BeatPrice.beat_id == beat_id, BeatPrice.is_active.is_(True))
        ).all()
        if set(active) <= {license_row.id}:
            raise ApiError(409, "LAST_ACTIVE_LICENSE")

    # ASSUMPTION: GAP-52 — a license missing from the beat is created by PUT
    if price is None:
        price = BeatPrice(beat_id=beat_id, license_id=license_row.id)
        db.add(price)
    price.price = Decimal(data.price)
    price.is_active = data.is_active
    db.commit()
    return build_cards(db, storage, [beat], owner_view=True)[0]


# --- Hide, return, delete (REST API §2.10, NFR-20) ---

def _guard_listed(beat: Beat) -> None:
    if beat.status == "reserved":
        raise ApiError(409, "BEAT_RESERVED")
    if beat.status == "sold":
        raise ApiError(409, "BEAT_SOLD")
    if beat.status not in ("active", "hidden"):
        raise ApiError(409, "INVALID_STATUS")


def change_status(db: Session, storage: ObjectStorage, user_id: int, beat_id: int, data: StatusChange) -> BeatOut:
    beat = _owned_beat(db, beat_id, user_id)
    _guard_listed(beat)
    beat.status = data.status
    db.commit()
    return build_cards(db, storage, [beat], owner_view=True)[0]


def delete_beat(db: Session, user_id: int, beat_id: int) -> None:
    """Logical deletion: purchased licenses and buyers' files stay (NFR-20)."""
    beat = _owned_beat(db, beat_id, user_id)
    _guard_listed(beat)
    beat.status = "deleted"
    db.commit()


# --- FR-8: beats stuck in `uploading` ---

def delete_abandoned_uploads(db: Session) -> int:
    """Run by the scheduler. The temporary files are removed by the lifecycle rule of temp-uploads."""
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().upload_ttl_hours)
    result = db.execute(
        update(Beat).where(Beat.status == "uploading", Beat.created_at < cutoff).values(status="deleted")
    )
    db.commit()
    return result.rowcount
