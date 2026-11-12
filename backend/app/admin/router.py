"""HTTP layer of the administration (REST API §2.13). Every endpoint: role `admin`, otherwise 403."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.admin import service
from app.admin.schemas import (
    AuditFacets,
    AuditPage,
    BeatStatus,
    GenreAdmin,
    GenreIn,
    RejectIn,
    StopWordIn,
    StopWordOut,
    StuckBeat,
)
from app.common.auth_deps import CurrentUser, client_ip, require_role
from app.common.db import get_db
from app.notifications.service import Notifier, get_notifier

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role("admin")


# --- Audit Log (FR-35, NFR-32): GET only ---

@router.get("/audit-log", response_model=AuditPage)
def audit_log(
    action: str | None = Query(None, max_length=64),
    entity: str | None = Query(None, max_length=64),
    entity_id: int | None = Query(None),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    cursor: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
) -> AuditPage:
    """Newest first. `action` ending with a dot is a group: `payment.` (GAP-75)."""
    return service.audit_log(db, action, entity, entity_id, date_from, date_to, cursor, limit)


@router.get("/audit-log/facets", response_model=AuditFacets)
def audit_facets(_: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)) -> AuditFacets:
    """Values for the filter menus (GAP-75)."""
    return service.audit_facets(db)


# --- Genres and the stop-list (FR-36) ---

@router.get("/genres", response_model=list[GenreAdmin])
def genres(_: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)) -> list[GenreAdmin]:
    return service.genres(db)


@router.post("/genres", status_code=status.HTTP_201_CREATED, response_model=GenreAdmin)
def add_genre(data: GenreIn, request: Request, user: CurrentUser = Depends(admin_only),
              db: Session = Depends(get_db)) -> GenreAdmin:
    """Errors: 400 VALIDATION_ERROR, 409 DUPLICATE (case-insensitive)."""
    return service.add_genre(db, user.id, data.name, client_ip(request))


@router.delete("/genres/{genre_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_genre(genre_id: int, request: Request, user: CurrentUser = Depends(admin_only),
                 db: Session = Depends(get_db)) -> Response:
    """Errors: 404, 409 GENRE_IN_USE."""
    service.delete_genre(db, user.id, genre_id, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stop-words", response_model=list[StopWordOut])
def stop_words(_: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)) -> list[StopWordOut]:
    return service.stop_words(db)


@router.post("/stop-words", status_code=status.HTTP_201_CREATED, response_model=StopWordOut)
def add_stop_word(data: StopWordIn, request: Request, user: CurrentUser = Depends(admin_only),
                  db: Session = Depends(get_db)) -> StopWordOut:
    """Stored in lower case with ё → е (GAP-16). Errors: 400 VALIDATION_ERROR, 409 DUPLICATE."""
    return service.add_stop_word(db, user.id, data.word, client_ip(request))


@router.delete("/stop-words/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stop_word(word_id: int, request: Request, user: CurrentUser = Depends(admin_only),
                     db: Session = Depends(get_db)) -> Response:
    service.delete_stop_word(db, user.id, word_id, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Stuck beats (FR-37) ---

@router.get("/beats", response_model=list[StuckBeat])
def processing_beats(
    status_filter: Literal["processing"] = Query("processing", alias="status"),
    all_: bool = Query(False, alias="all"),
    _: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
) -> list[StuckBeat]:
    """Beats in `processing`: by default only the stuck ones (GAP-21, GAP-74); `all=true` — every one."""
    return service.processing_beats(db, include_recent=all_)


@router.post("/beats/{beat_id}/reprocess", status_code=status.HTTP_202_ACCEPTED, response_model=BeatStatus)
def reprocess(beat_id: int, request: Request, user: CurrentUser = Depends(admin_only),
              db: Session = Depends(get_db)) -> BeatStatus:
    """A new task for Media Worker through the outbox. Errors: 404, 409 INVALID_STATUS."""
    return service.reprocess(db, user.id, beat_id, client_ip(request))


@router.post("/beats/{beat_id}/reject", response_model=BeatStatus)
def reject(beat_id: int, data: RejectIn, request: Request, user: CurrentUser = Depends(admin_only),
           db: Session = Depends(get_db), notifier: Notifier = Depends(get_notifier)) -> BeatStatus:
    """`rejected` with the reason, an email to the Producer. Errors: 400, 404, 409 INVALID_STATUS."""
    result, (to, subject, body) = service.reject(db, user.id, beat_id, data.reason, client_ip(request))
    notifier.send_email(to, subject, body)  # after the commit (GAP-55)
    return result
