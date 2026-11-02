"""Outbox relay on a real RabbitMQ (test virtual host): RabbitMQ_Worker.md §2, FR-7."""

import json

import pytest
from sqlalchemy import text

from app.background.relay import publish_batch
from app.common.db import get_session_factory
from app.common.rabbit import PROCESSING_QUEUE


def _add_outbox_row(owner_engine, beat_id: int = 1) -> str:
    with get_session_factory()() as db:
        from app.common.outbox import add_event

        event = add_event(db, "beat.media.process", {"beat_id": beat_id, "files": {}, "options": {}})
        db.commit()
        return str(event.id)


def _drain(channel) -> list[dict]:
    messages = []
    while True:
        method, properties, body = channel.basic_get(PROCESSING_QUEUE, auto_ack=True)
        if method is None:
            return messages
        messages.append({"body": json.loads(body), "message_id": properties.message_id,
                         "persistent": properties.delivery_mode == 2})


@pytest.fixture
def publisher(rabbit_channel):
    """The relay publishes on its own channel with publisher confirms."""
    from app.common.rabbit import connect

    connection = connect()
    channel = connection.channel()
    channel.confirm_delivery()
    yield channel
    connection.close()


def test_relay_publishes_and_marks_rows(owner_engine, rabbit_channel, publisher):
    event_id = _add_outbox_row(owner_engine)
    with get_session_factory()() as db:
        assert publish_batch(db, publisher) == 1

    messages = _drain(rabbit_channel)
    assert len(messages) == 1
    assert messages[0]["body"]["event_id"] == event_id
    assert messages[0]["message_id"] == event_id
    assert messages[0]["persistent"] is True
    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT published_at IS NOT NULL FROM outbox")) is True

    # A second pass sends nothing: the row is already marked
    with get_session_factory()() as db:
        assert publish_batch(db, publisher) == 0
    assert _drain(rabbit_channel) == []


def test_relay_crash_after_publish_sends_again_at_least_once(owner_engine, rabbit_channel, publisher, monkeypatch):
    """The relay published but died before marking published_at: the message goes out again.
    Consumers must be idempotent (RabbitMQ_Worker.md §2 p.3)."""
    event_id = _add_outbox_row(owner_engine)
    with get_session_factory()() as db:
        def crash():
            raise RuntimeError("relay process killed")

        monkeypatch.setattr(db, "commit", crash)
        with pytest.raises(RuntimeError):
            publish_batch(db, publisher)
        db.rollback()

    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT published_at FROM outbox")) is None

    with get_session_factory()() as db:
        assert publish_batch(db, publisher) == 1
    messages = _drain(rabbit_channel)
    assert [m["body"]["event_id"] for m in messages] == [event_id, event_id]  # a duplicate, by design


def test_relay_two_instances_do_not_take_the_same_rows(owner_engine, publisher, rabbit_channel):
    """FOR UPDATE SKIP LOCKED: while one relay holds rows, another one skips them."""
    _add_outbox_row(owner_engine)
    factory = get_session_factory()
    with factory() as first, factory() as second:
        from sqlalchemy import select

        from app.common.outbox import OutboxEvent

        first.scalars(select(OutboxEvent).with_for_update(skip_locked=True)).all()  # holds the lock
        assert publish_batch(second, publisher) == 0
        first.rollback()
    with factory() as db:
        assert publish_batch(db, publisher) == 1
