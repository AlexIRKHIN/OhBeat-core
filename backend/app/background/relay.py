"""Outbox relay (RabbitMQ_Worker.md §2): once a second publishes new outbox rows to RabbitMQ.

    1. SELECT unpublished rows FOR UPDATE SKIP LOCKED — two relays never take the same row;
    2. publish each one and wait for the publisher confirm ("the broker has stored it");
    3. UPDATE published_at.

If the relay dies between 2 and 3, the row is published again on the next run.
Delivery is "at least once", so consumers are idempotent.

Run:  python -m app.background.relay
"""

import json
import logging
import time

import pika
from pika.exceptions import AMQPError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.db import get_session_factory
from app.common.outbox import OutboxEvent
from app.common.rabbit import EXCHANGE, connect, declare_topology

log = logging.getLogger("relay")


def publish_batch(db: Session, channel) -> int:
    """One pass of the relay. Returns the number of published events."""
    rows = db.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.created_at)
        .limit(get_settings().relay_batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    published = 0
    try:
        for row in rows:
            channel.basic_publish(
                exchange=EXCHANGE,
                routing_key=row.event_type,
                body=json.dumps(row.payload).encode(),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,  # survives a broker restart
                    message_id=str(row.id),
                    type=row.event_type,
                ),
                mandatory=True,  # no bound queue -> error instead of a silently lost message
            )
            row.published_at = func.now()
            published += 1
    finally:
        # Rows published before a failure are marked; the rest stay for the next pass
        db.commit()
    return published


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("pika").setLevel(logging.CRITICAL)  # our own warning below is enough
    settings = get_settings()
    session_factory = get_session_factory()
    connection = None
    while True:
        try:
            if connection is None or connection.is_closed:
                connection = connect()
                channel = connection.channel()
                channel.confirm_delivery()  # basic_publish now waits for the broker's confirm
                declare_topology(channel)
                log.info("connected to RabbitMQ")
            with session_factory() as db:
                count = publish_batch(db, channel)
            if count:
                log.info("published %s event(s)", count)
            connection.process_data_events(time_limit=settings.relay_interval_seconds)
        except AMQPError as exc:
            log.warning("RabbitMQ is unavailable (%s), retrying in 5 s", exc.__class__.__name__)
            connection = None
            time.sleep(5)
        except Exception:
            log.exception("relay pass failed, retrying in 5 s")
            time.sleep(5)


if __name__ == "__main__":
    run_forever()
