"""Audit Log: append-only journal (NFR-7, NFR-32).

The application role has no UPDATE, DELETE or TRUNCATE on this table, so the
only operation offered here is adding a record. It is written in the same
transaction as the change it describes.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict | None] = mapped_column(JSONB)


def write_audit(
    db: Session,
    *,
    action: str,
    entity: str,
    entity_id: int | None,
    actor_user_id: int | None,
    ip: str | None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity=entity,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            ip=ip,
            details=details,
        )
    )
