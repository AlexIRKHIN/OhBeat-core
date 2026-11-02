"""Results of media processing in Core API: FR-12, RabbitMQ_Worker.md §4–§5.

Includes the mandatory test: repeated delivery of a message from the queue.
"""

import json
import threading
import time
import uuid

import pika
import pytest
from sqlalchemy import text

from app.catalog.media_results import ResultNotReady, apply_result
from app.common.config import get_settings
from app.common.db import get_session_factory
from app.common.rabbit import EXCHANGE, PROCESSED_KEY, RESULTS_QUEUE, connect
from app.common.storage import _client, get_storage
from tests.helpers import auth, beat_body, make_producer


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []
        self.lock = threading.Lock()

    def send_email(self, to: str, subject: str, body: str) -> None:
        with self.lock:
            self.sent.append((to, subject, body))


@pytest.fixture
def processing_beat(client, owner_engine) -> int:
    """A beat in `processing`: created through the API, the status set directly (uploads are tested elsewhere)."""
    producer = make_producer(client)
    beat_id = client.post("/v1/beats", json=beat_body(), headers=auth(producer)).json()["id"]
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE beats SET status = 'processing' WHERE id = :id"), {"id": beat_id})
    return beat_id


def _put_outputs(beat_id: int) -> dict:
    """Puts the objects Media Worker would have produced, with the sha256 metadata (GAP-50)."""
    s3 = _client(get_settings().s3_internal_endpoint)
    settings = get_settings()
    outputs = {
        "master": (settings.bucket_private, f"beats/{beat_id}/master.wav"),
        "stems": (settings.bucket_private, f"beats/{beat_id}/stems.zip"),
        "clean_mp3": (settings.bucket_private, f"beats/{beat_id}/clean.mp3"),
        "preview_mp3": (settings.bucket_public, f"previews/{beat_id}_v1.mp3"),
        "cover": (settings.bucket_public, f"covers/{beat_id}_v1.jpg"),
    }
    for kind, (bucket, key) in outputs.items():
        s3.put_object(Bucket=bucket, Key=key, Body=kind.encode() * 10, Metadata={"sha256": kind[0] * 64})
    return {kind: key for kind, (_, key) in outputs.items()}


def _processed(beat_id: int, outputs: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()), "event_type": "beat.media.processed", "occurred_at": "2026-11-02T10:00:00Z",
        "source_event_id": str(uuid.uuid4()), "beat_id": beat_id, "result": "processed",
        "duration_sec": 184, "outputs": outputs, "error": None,
    }


def _rejected(beat_id: int) -> dict:
    return {
        "event_id": str(uuid.uuid4()), "event_type": "beat.media.processed", "occurred_at": "2026-11-02T10:00:00Z",
        "source_event_id": str(uuid.uuid4()), "beat_id": beat_id, "result": "rejected",
        "duration_sec": None, "outputs": None,
        "error": {"code": "ARCHIVE_CONTAINS_NON_AUDIO", "message": "В архиве найдены файлы, кроме WAV: readme.exe"},
    }


def _apply(message: dict, notifier) -> str:
    with get_session_factory()() as db:
        return apply_result(db, get_storage(), notifier, message).status


def test_fr12_processed_makes_beat_active_with_files(processing_beat, owner_engine):
    notifier = FakeNotifier()
    assert _apply(_processed(processing_beat, _put_outputs(processing_beat)), notifier) == "active"

    with owner_engine.connect() as conn:
        beat = conn.execute(text("SELECT status, published_at, duration_sec FROM beats WHERE id = :id"),
                            {"id": processing_beat}).one()
        files = {r.kind: r for r in conn.execute(
            text("SELECT kind, storage_key, size_bytes, sha256 FROM beat_files WHERE beat_id = :id"), {"id": processing_beat})}
    assert beat.status == "active" and beat.published_at is not None and beat.duration_sec == 184
    assert set(files) == {"master", "stems", "clean_mp3", "preview_mp3", "cover"}
    assert files["preview_mp3"].storage_key == f"previews/{processing_beat}_v1.mp3"
    assert files["master"].size_bytes == len(b"master" * 10)  # real size from HeadObject
    assert files["clean_mp3"].sha256 == "c" * 64
    assert len(notifier.sent) == 1 and "опубликован" in notifier.sent[0][1]


def test_fr12_rejected_keeps_reason_and_notifies(processing_beat, owner_engine):
    notifier = FakeNotifier()
    assert _apply(_rejected(processing_beat), notifier) == "rejected"
    with owner_engine.connect() as conn:
        beat = conn.execute(text("SELECT status, rejection_reason FROM beats WHERE id = :id"), {"id": processing_beat}).one()
    assert beat.status == "rejected"
    assert beat.rejection_reason == "В архиве найдены файлы, кроме WAV: readme.exe"
    assert "readme.exe" in notifier.sent[0][2]


def test_repeated_delivery_changes_beat_once(processing_beat, owner_engine):
    """MANDATORY: the same result delivered again is acknowledged without changes and without a second email."""
    notifier = FakeNotifier()
    message = _processed(processing_beat, _put_outputs(processing_beat))
    assert _apply(message, notifier) == "active"
    assert _apply(message, notifier) == "skipped"
    # Even a contradicting late message (e.g. a stale "rejected") cannot change a finished beat
    assert _apply(_rejected(processing_beat), notifier) == "skipped"
    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM beats WHERE id = :id"), {"id": processing_beat}) == "active"
        assert conn.scalar(text("SELECT count(*) FROM beat_files WHERE beat_id = :id"), {"id": processing_beat}) == 5
    assert len(notifier.sent) == 1


def test_repeated_delivery_in_parallel_applies_once(processing_beat):
    """MANDATORY: three copies arrive at the same moment; the row lock lets only one of them through."""
    notifier = FakeNotifier()
    message = _processed(processing_beat, _put_outputs(processing_beat))
    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(_apply(message, notifier))) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(results) == ["active", "skipped", "skipped"]
    assert len(notifier.sent) == 1


def test_missing_output_is_temporary_and_changes_nothing(processing_beat, owner_engine):
    message = _processed(processing_beat, _put_outputs(processing_beat))
    message["outputs"]["clean_mp3"] = f"beats/{processing_beat}/does-not-exist.mp3"
    with pytest.raises(ResultNotReady):
        _apply(message, FakeNotifier())
    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM beats WHERE id = :id"), {"id": processing_beat}) == "processing"


# --- The consumer on a real RabbitMQ: retries and the DLQ (RabbitMQ_Worker.md §5, GAP-20, GAP-51) ---

def _publish_result(message: dict) -> None:
    connection = connect()
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_publish(EXCHANGE, PROCESSED_KEY, json.dumps(message).encode(),
                          pika.BasicProperties(delivery_mode=2, message_id=message["event_id"]), mandatory=True)
    connection.close()


def _consume_for(seconds: float) -> None:
    from app.background.media_results import handle

    connection = connect()
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_consume(RESULTS_QUEUE, handle)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        connection.process_data_events(time_limit=0.2)
    connection.close()


def test_consumer_applies_result_and_acks(rabbit_channel, processing_beat, owner_engine):
    _publish_result(_processed(processing_beat, _put_outputs(processing_beat)))
    _consume_for(2)
    with owner_engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM beats WHERE id = :id"), {"id": processing_beat}) == "active"
    assert rabbit_channel.queue_declare(RESULTS_QUEUE, passive=True).method.message_count == 0


def test_temporary_failure_retried_three_times_then_dlq(rabbit_channel, processing_beat, monkeypatch):
    """1 attempt + 3 retries through the delay queues, then the message lands in beat_results_dlq."""
    attempts = []

    def failing(*args, **kwargs):
        attempts.append(1)
        raise ResultNotReady("S3 is unavailable")

    monkeypatch.setattr("app.background.media_results.apply_result", failing)
    rabbit_channel.queue_purge("beat_results_dlq")
    _publish_result(_rejected(processing_beat))
    _consume_for(4)

    assert len(attempts) == 4
    method, properties, _ = rabbit_channel.basic_get("beat_results_dlq", auto_ack=True)
    assert method is not None, "the message must be in the DLQ"
    expired = [d for d in properties.headers["x-death"] if d["reason"] == "expired"]
    assert sum(d["count"] for d in expired) == 3


def test_malformed_result_goes_straight_to_dlq(rabbit_channel):
    rabbit_channel.queue_purge("beat_results_dlq")
    _publish_result({"event_id": str(uuid.uuid4()), "something": "else"})
    _consume_for(1)
    assert rabbit_channel.basic_get("beat_results_dlq", auto_ack=True)[0] is not None
