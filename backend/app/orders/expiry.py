"""FR-29: once a minute the scheduler releases expired reservations and expires unpaid orders.

Both statements are taken from Database_Schema.md §6 as they are. Each is one UPDATE whose
conditions are checked on the row being changed, so a beat sold meanwhile (FR-23) is left alone
and two schedulers running at once do no harm.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.config import get_settings

# 1. Expired Exclusive reservations: the beat is for sale again, its order expires.
#    `beats old` gives the reserved_order_id BEFORE the update (RETURNING shows the new NULL).
RELEASE_RESERVATIONS = text("""
WITH expired AS (
    UPDATE beats b
    SET status = 'active', reserved_order_id = NULL, reserved_until = NULL
    FROM beats old
    WHERE old.id = b.id
      AND b.status = 'reserved'
      AND b.reserved_until < now()
    RETURNING old.reserved_order_id
)
UPDATE orders o
SET status = 'expired'
WHERE o.status = 'pending'
  AND o.id IN (SELECT reserved_order_id FROM expired)
RETURNING o.id
""")

# 2. Orders without Exclusive not paid within 24 hours.
EXPIRE_UNPAID = text("""
UPDATE orders o
SET status = 'expired'
WHERE o.status = 'pending'
  AND o.created_at < now() - make_interval(hours => :hours)
  AND NOT EXISTS (
      SELECT 1
      FROM order_items oi
      JOIN licenses l ON l.id = oi.license_id
      WHERE oi.order_id = o.id AND l.is_exclusive
  )
RETURNING o.id
""")


def expire_reservations(db: Session) -> int:
    released = db.execute(RELEASE_RESERVATIONS).scalars().all()
    unpaid = db.execute(EXPIRE_UNPAID, {"hours": get_settings().unpaid_order_ttl_hours}).scalars().all()
    db.commit()
    return len(released) + len(unpaid)
