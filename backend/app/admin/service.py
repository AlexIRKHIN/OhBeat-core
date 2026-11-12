"""Administration (FR-35 … FR-37, REST API §2.13).

* Audit Log — read only (NFR-32): the application role has no UPDATE/DELETE on it, and there is no
  endpoint that would try.
* Dictionaries — genres and the stop-list; a genre used by any beat stays (FR-36).
* Stuck beats — still `processing` after all retries of Media Worker; "process again" adds a new task
  to the outbox, "reject" ends the processing with a reason (FR-37).
"""

import base64
import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.schemas import (
    Actor,
    AuditEntry,
    AuditFacets,
    AuditPage,
    BeatStatus,
    GenreAdmin,
    StopWordOut,
    StuckBeat,
)
from app.catalog.models import Beat, BeatGenre, StopWord
from app.catalog.service import enqueue_processing
from app.catalog.stoplist import normalize
from app.common.audit import AuditLog, write_audit
from app.common.config import get_settings
from app.common.errors import ApiError, field_error
from app.common.i18n import t
from app.common.outbox import OutboxEvent
from app.common.rabbit import PROCESS_KEY
from app.contracts.issue import MSK
from app.dictionaries.models import Genre
from app.users.models import Profile, User

# --- Audit Log (FR-35, ASSUMPTION: GAP-75) ---

def _encode(entry: AuditLog) -> str:
    raw = json.dumps({"t": entry.occurred_at.isoformat(), "id": entry.id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode(cursor: str) -> tuple[datetime, int]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return datetime.fromisoformat(data["t"]), int(data["id"])
    except (ValueError, KeyError, TypeError):
        raise field_error("cursor", "invalid_value") from None


def audit_log(db: Session, action: str | None, entity: str | None, entity_id: int | None,
              date_from: date | None, date_to: date | None, cursor: str | None, limit: int) -> AuditPage:
    query = select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.actor_user_id)
    if action:
        # "payment." — every action of the group; otherwise the exact name
        query = query.where(AuditLog.action.startswith(action, autoescape=True) if action.endswith(".")
                            else AuditLog.action == action)
    if entity:
        query = query.where(AuditLog.entity == entity)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if date_from and date_to and date_from > date_to:
        raise field_error("from", "period_reversed")
    if date_from:  # Moscow calendar days, both ends included (as GAP-69)
        query = query.where(AuditLog.occurred_at >= datetime.combine(date_from, datetime.min.time(), MSK))
    if date_to:
        query = query.where(AuditLog.occurred_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), MSK))
    if cursor:
        at, entry_id = _decode(cursor)
        query = query.where((AuditLog.occurred_at < at) | ((AuditLog.occurred_at == at) & (AuditLog.id < entry_id)))
    rows = db.execute(query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit + 1)).all()

    page = rows[:limit]
    items = [AuditEntry(
        id=row.AuditLog.id, occurred_at=row.AuditLog.occurred_at, action=row.AuditLog.action,
        entity=row.AuditLog.entity, entity_id=row.AuditLog.entity_id,
        actor=Actor(id=row.AuditLog.actor_user_id, email=row.email) if row.AuditLog.actor_user_id else None,
        ip=row.AuditLog.ip, details=row.AuditLog.details,
    ) for row in page]
    return AuditPage(items=items, next_cursor=_encode(page[-1].AuditLog) if len(rows) > limit else None)


def audit_facets(db: Session) -> AuditFacets:
    return AuditFacets(
        actions=list(db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action))),
        entities=list(db.scalars(select(AuditLog.entity).distinct().order_by(AuditLog.entity))),
    )


# --- Genres (FR-36, ASSUMPTION: GAP-76) ---

def genres(db: Session) -> list[GenreAdmin]:
    counts = (select(BeatGenre.genre_id, func.count().label("n")).group_by(BeatGenre.genre_id)).subquery()
    rows = db.execute(select(Genre, func.coalesce(counts.c.n, 0))
                      .outerjoin(counts, counts.c.genre_id == Genre.id).order_by(Genre.name)).all()
    return [GenreAdmin(id=g.id, name=g.name, beats_count=n) for g, n in rows]


def add_genre(db: Session, admin_id: int, name: str, ip: str | None) -> GenreAdmin:
    name = re.sub(r"\s+", " ", name)
    if db.scalar(select(Genre.id).where(func.lower(Genre.name) == name.lower())):
        raise ApiError(409, "DUPLICATE", [{"field": "name", "issue": t("duplicate_values")}])
    genre = Genre(name=name)
    db.add(genre)
    db.flush()
    write_audit(db, action="admin.genre_created", entity="genre", entity_id=genre.id, actor_user_id=admin_id, ip=ip,
                details={"name": name})
    db.commit()
    return GenreAdmin(id=genre.id, name=genre.name, beats_count=0)


def delete_genre(db: Session, admin_id: int, genre_id: int, ip: str | None) -> None:
    genre = db.scalar(select(Genre).where(Genre.id == genre_id).with_for_update())
    if genre is None:
        raise ApiError(404, "NOT_FOUND")
    # Also beats deleted logically: bought licenses refer to them, and the FK is RESTRICT anyway
    used = db.scalar(select(func.count()).select_from(BeatGenre).where(BeatGenre.genre_id == genre_id))
    if used:
        raise ApiError(409, "GENRE_IN_USE", [{"field": "id", "issue": t("genre_in_use", count=used), "beats_count": used}])
    db.delete(genre)
    write_audit(db, action="admin.genre_deleted", entity="genre", entity_id=genre_id, actor_user_id=admin_id, ip=ip,
                details={"name": genre.name})
    db.commit()


# --- Stop-list (FR-36, GAP-16, ASSUMPTION: GAP-76) ---

STOP_WORD = re.compile(r"^[\w-]+( [\w-]+)*$")


def stop_words(db: Session) -> list[StopWordOut]:
    return [StopWordOut(id=w.id, word=w.word, created_at=w.created_at)
            for w in db.scalars(select(StopWord).order_by(StopWord.word))]


def add_stop_word(db: Session, admin_id: int, word: str, ip: str | None) -> StopWordOut:
    word = normalize(re.sub(r"\s+", " ", word))  # stored the way it is compared: lower case, ё → е
    if not STOP_WORD.match(word) or "_" in word:
        raise field_error("word", "stop_word_format")
    if db.scalar(select(StopWord.id).where(StopWord.word == word)):
        raise ApiError(409, "DUPLICATE", [{"field": "word", "issue": t("duplicate_values")}])
    row = StopWord(word=word)
    db.add(row)
    db.flush()
    write_audit(db, action="admin.stop_word_added", entity="stop_word", entity_id=row.id, actor_user_id=admin_id, ip=ip,
                details={"word": word})
    db.commit()
    db.refresh(row)
    return StopWordOut(id=row.id, word=row.word, created_at=row.created_at)


def delete_stop_word(db: Session, admin_id: int, word_id: int, ip: str | None) -> None:
    row = db.get(StopWord, word_id)
    if row is None:
        raise ApiError(404, "NOT_FOUND")
    db.delete(row)
    write_audit(db, action="admin.stop_word_deleted", entity="stop_word", entity_id=word_id, actor_user_id=admin_id,
                ip=ip, details={"word": row.word})
    db.commit()


# --- Stuck beats (FR-37, ASSUMPTION: GAP-21, GAP-74) ---

def _processing_since():
    """The time of the latest processing task of the beat in the outbox (rows stay after publishing)."""
    return (
        select(func.max(OutboxEvent.created_at))
        .where(OutboxEvent.event_type == PROCESS_KEY, OutboxEvent.payload["beat_id"].as_integer() == Beat.id)
        .correlate(Beat)
        .scalar_subquery()
    )


def processing_beats(db: Session, include_recent: bool) -> list[StuckBeat]:
    since = func.coalesce(_processing_since(), Beat.created_at).label("since")
    border = func.now() - func.make_interval(0, 0, 0, 0, 0, get_settings().stuck_processing_minutes)
    rows = db.execute(
        select(Beat.id, Beat.title, Beat.producer_id, Profile.display_name, since, (since < border).label("stuck"))
        .join(Profile, Profile.user_id == Beat.producer_id)
        .where(Beat.status == "processing")
        .order_by(since)
    ).all()
    return [StuckBeat(id=r.id, title=r.title, producer=r.display_name, producer_id=r.producer_id,
                      processing_since=r.since, stuck=r.stuck)
            for r in rows if include_recent or r.stuck]


def _processing_beat(db: Session, beat_id: int) -> Beat:
    beat = db.scalar(select(Beat).where(Beat.id == beat_id).with_for_update())
    if beat is None:
        raise ApiError(404, "NOT_FOUND")
    if beat.status != "processing":
        raise ApiError(409, "INVALID_STATUS")  # already published or rejected meanwhile
    return beat


def reprocess(db: Session, admin_id: int, beat_id: int, ip: str | None) -> BeatStatus:
    beat = _processing_beat(db, beat_id)
    enqueue_processing(db, beat)  # a new task: the old message stays in the DLQ (ASSUMPTION: GAP-77)
    write_audit(db, action="admin.beat_reprocessed", entity="beat", entity_id=beat.id, actor_user_id=admin_id, ip=ip,
                details={"title": beat.title})
    db.commit()
    return BeatStatus(id=beat.id, status=beat.status)


def reject(db: Session, admin_id: int, beat_id: int, reason: str, ip: str | None) -> tuple[BeatStatus, tuple[str, str, str]]:
    """Returns the status and the email for the Producer: it is sent after the commit (GAP-55)."""
    beat = _processing_beat(db, beat_id)
    beat.status = "rejected"
    beat.rejection_reason = reason  # ASSUMPTION: GAP-19 — shown as is in both languages
    write_audit(db, action="admin.beat_rejected", entity="beat", entity_id=beat.id, actor_user_id=admin_id, ip=ip,
                details={"title": beat.title, "reason": reason})
    email = db.scalar(select(User.email).where(User.id == beat.producer_id))
    db.commit()
    return BeatStatus(id=beat.id, status=beat.status), (
        email,
        f"Бит «{beat.title}» отклонён",
        f"Ваш бит «{beat.title}» не прошёл проверку: {reason}. "
        "Исправьте файл и загрузите бит заново в разделе «Мои биты».",
    )
