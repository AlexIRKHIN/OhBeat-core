"""Applying `beat.media.processed` (FR-12, RabbitMQ_Worker.md §4).

Idempotent: the result is applied only while the beat is still `processing` (the row is locked).
A repeated delivery of the same message finds another status and changes nothing.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.models import Beat, BeatFile
from app.common.config import get_settings
from app.common.storage import ObjectStorage, StorageUnavailable
from app.notifications.service import Notifier
from app.users.models import User

log = logging.getLogger("media-results")

# Output kind -> bucket (FR-11: originals and the clean MP3 private, preview and cover public)
PUBLIC_KINDS = {"preview_mp3", "cover"}
OUTPUT_KINDS = ("master", "stems", "clean_mp3", "preview_mp3", "cover")


class ResultNotReady(Exception):
    """An output object is missing in S3 or S3 is down: a temporary problem, the message is retried."""


@dataclass
class Applied:
    beat_id: int
    status: str  # active | rejected | skipped


def _bucket(kind: str) -> str:
    settings = get_settings()
    return settings.bucket_public if kind in PUBLIC_KINDS else settings.bucket_private


def apply_result(db: Session, storage: ObjectStorage, notifier: Notifier, message: dict) -> Applied:
    beat_id = int(message["beat_id"])
    beat = db.scalar(select(Beat).where(Beat.id == beat_id).with_for_update())
    if beat is None or beat.status != "processing":
        # Duplicate delivery or a beat already handled by the Administrator: acknowledge, change nothing
        db.rollback()
        log.info("beat %s: result %s skipped (status %s)", beat_id, message.get("event_id"), beat and beat.status)
        return Applied(beat_id, "skipped")

    if message["result"] == "processed":
        outputs = message.get("outputs") or {}
        files = {f.kind: f for f in db.scalars(select(BeatFile).where(BeatFile.beat_id == beat_id))}
        for kind in OUTPUT_KINDS:
            key = outputs.get(kind)
            if not key:
                continue
            try:
                # ASSUMPTION: GAP-50 — size and SHA-256 are read from the object itself
                info = storage.head(_bucket(kind), key)
            except StorageUnavailable as exc:
                raise ResultNotReady(f"S3 is unavailable: {exc}") from exc
            if info is None:
                raise ResultNotReady(f"output {kind} {key} not found")
            row = files.get(kind) or BeatFile(beat_id=beat_id, kind=kind)
            row.storage_key, row.size_bytes, row.sha256 = key, info.size_bytes, info.sha256
            db.add(row)
        beat.status = "active"
        beat.published_at = func.now()  # FR-12: "active with the publication date"
        beat.duration_sec = message.get("duration_sec")
        beat.rejection_reason = None
        subject, body = (
            f"Бит «{beat.title}» опубликован",
            f"Ваш бит «{beat.title}» прошёл проверку и появился в каталоге OhBeat.",
        )
    else:
        error = message.get("error") or {}
        beat.status = "rejected"
        beat.rejection_reason = error.get("message") or error.get("code") or "Файлы не прошли проверку"
        subject, body = (
            f"Бит «{beat.title}» отклонён",
            f"Ваш бит «{beat.title}» не прошёл проверку: {beat.rejection_reason}. "
            "Исправьте файл и загрузите бит заново в разделе «Мои биты».",
        )

    email = db.scalar(select(User.email).where(User.id == beat.producer_id))
    db.commit()
    log.info("beat %s: %s (source event %s)", beat_id, beat.status, message.get("source_event_id"))

    # After the commit: the status is saved even if the provider fails (GAP-55)
    try:
        notifier.send_email(email, subject, body)
    except Exception:
        log.exception("beat %s: notification failed", beat_id)
    return Applied(beat_id, beat.status)
