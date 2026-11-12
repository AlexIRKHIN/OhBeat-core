"""Bodies of the administration endpoints (REST API §2.13, FR-35 … FR-37)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints


class Actor(BaseModel):
    id: int
    email: str | None


class AuditEntry(BaseModel):
    id: int
    occurred_at: datetime
    action: str
    entity: str
    entity_id: int | None
    actor: Actor | None
    ip: str | None
    details: dict | None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_cursor: str | None


class AuditFacets(BaseModel):
    actions: list[str]
    entities: list[str]


class GenreAdmin(BaseModel):
    id: int
    name: str
    beats_count: int


class GenreIn(BaseModel):
    # ASSUMPTION: GAP-76 — 2–64 characters (genres.name is varchar(64))
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]


class StopWordOut(BaseModel):
    id: int
    word: str
    created_at: datetime


class StopWordIn(BaseModel):
    word: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


class StuckBeat(BaseModel):
    id: int
    title: str
    producer: str
    producer_id: int
    processing_since: datetime
    stuck: bool


class RejectIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class BeatStatus(BaseModel):
    id: int
    status: str
