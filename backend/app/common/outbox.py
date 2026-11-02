"""Transactional outbox (RabbitMQ_Worker.md §2).

Instead of sending a message to RabbitMQ directly, a service adds a row to `outbox`
in the SAME transaction as the business change. Either both are saved or neither.
The relay process (app/background/relay.py) later publishes the row to the broker.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.db import Base


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64))  # also the RabbitMQ routing key
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def add_event(db: Session, event_type: str, body: dict) -> OutboxEvent:
    """Adds an event to the current transaction. `event_id` of the message equals the row id."""
    event_id = uuid.uuid4()
    payload = {
        "event_id": str(event_id),
        "event_type": event_type,
        "occurred_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **body,
    }
    event = OutboxEvent(id=event_id, event_type=event_type, payload=payload)
    db.add(event)
    return event
