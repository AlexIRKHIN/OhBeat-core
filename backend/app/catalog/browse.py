"""Public catalog and producer showcase (REST API §2.3, §2.9; US-A2, US-P5, UC-1, UC-2).

One SQL query with optional filters and keyset pagination:

    WHERE status IN ('active', 'reserved')            -- sold, hidden, deleted... are not shown (FR-24)
      AND <filters>
      AND (published_at, id) < (<cursor>)              -- the next page: everything older than the last card
    ORDER BY published_at DESC, id DESC                -- "newest first", uses idx_beats_catalog
    LIMIT limit + 1                                    -- one extra row tells whether there is a next page

A new beat published while somebody is paging appears before page 1 and never shifts later pages.
"""

import base64
import json
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import exists, func, select, tuple_
from sqlalchemy.orm import Session

from app.catalog.models import Beat, BeatGenre, BeatPrice
from app.catalog.schemas import BeatPage, ProducerPage
from app.catalog.service import PUBLIC_STATUSES, build_cards
from app.common.errors import ApiError
from app.common.i18n import t
from app.common.storage import ObjectStorage
from app.dictionaries.models import Genre
from app.users.models import Profile, UserRole


@dataclass(frozen=True)
class CatalogFilters:
    genre: str | None = None
    bpm_min: int | None = None
    bpm_max: int | None = None
    musical_key: str | None = None
    price_max: int | None = None
    producer_id: int | None = None


def _invalid(field: str) -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", [{"field": field, "issue": t("invalid_value")}])


def encode_cursor(beat: Beat) -> str:
    raw = json.dumps({"p": beat.published_at.isoformat(), "id": beat.id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return datetime.fromisoformat(data["p"]), int(data["id"])
    except (ValueError, KeyError, TypeError):
        raise _invalid("cursor") from None


def browse(
    db: Session, storage: ObjectStorage, filters: CatalogFilters, cursor: str | None, limit: int
) -> BeatPage:
    # ASSUMPTION: GAP-59 — contradictory bounds are an error, not an empty page
    if filters.bpm_min is not None and filters.bpm_max is not None and filters.bpm_min > filters.bpm_max:
        raise _invalid("bpm_min")

    query = select(Beat).where(
        Beat.status.in_(PUBLIC_STATUSES),
        Beat.published_at.is_not(None),  # always set for a published beat (FR-12); keeps the cursor well-defined
    )
    if filters.producer_id is not None:
        query = query.where(Beat.producer_id == filters.producer_id)
    if filters.genre:
        # ASSUMPTION: GAP-59 — an unknown genre (e.g. deleted by the Administrator) gives an empty page
        query = query.where(
            exists().where(
                BeatGenre.beat_id == Beat.id,
                BeatGenre.genre_id == Genre.id,
                func.lower(Genre.name) == filters.genre.lower(),
            )
        )
    if filters.bpm_min is not None:
        query = query.where(Beat.bpm >= filters.bpm_min)
    if filters.bpm_max is not None:
        query = query.where(Beat.bpm <= filters.bpm_max)
    if filters.musical_key:
        query = query.where(Beat.musical_key == filters.musical_key)
    if filters.price_max is not None:
        # REST API §2.3: compared with the LOWEST price among active licenses.
        # "Some active license costs <= max" is exactly "the lowest active price <= max".
        query = query.where(
            exists().where(
                BeatPrice.beat_id == Beat.id,
                BeatPrice.is_active.is_(True),
                BeatPrice.price <= filters.price_max,
            )
        )
    if cursor:
        published_at, beat_id = decode_cursor(cursor)
        query = query.where(tuple_(Beat.published_at, Beat.id) < tuple_(published_at, beat_id))

    # ASSUMPTION: GAP-61 — "newest" means the first publication date
    rows = list(db.scalars(query.order_by(Beat.published_at.desc(), Beat.id.desc()).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    return BeatPage(
        items=build_cards(db, storage, page, owner_view=False),
        next_cursor=encode_cursor(page[-1]) if more else None,
    )


def producer_page(
    db: Session, storage: ObjectStorage, producer_id: int, filters: CatalogFilters, cursor: str | None, limit: int
) -> ProducerPage:
    # ASSUMPTION: GAP-58 — only a connected Producer has a public page
    is_producer = db.scalar(
        select(UserRole.user_id).where(UserRole.user_id == producer_id, UserRole.role == "producer")
    )
    profile = db.get(Profile, producer_id)
    if not is_producer or profile is None:
        raise ApiError(404, "NOT_FOUND")
    page = browse(db, storage, replace(filters, producer_id=producer_id), cursor, limit)
    return ProducerPage(
        id=producer_id,
        display_name=profile.display_name,
        bio=profile.bio,
        avatar_url=storage.public_url(profile.avatar_key) if profile.avatar_key else None,
        items=page.items,
        next_cursor=page.next_cursor,
    )
