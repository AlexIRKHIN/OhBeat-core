"""The consumer on a real RabbitMQ: result publishing, retries 30 s / 2 min / 10 min (shortened), DLQ.

RabbitMQ_Worker.md §5, GAP-51.
"""

import dataclasses
import json
import time
import uuid

import pika
import pytest

from worker import main
from worker.rabbit import EXCHANGE, PROCESS_KEY, PROCESSING_QUEUE, RESULTS_QUEUE, connect, declare_topology


@pytest.fixture
def channel(rabbit_vhost, settings):
    connection = connect(settings.rabbitmq_url)
    ch = connection.channel()
    declare_topology(ch, settings.retry_delays)
    for queue in (PROCESSING_QUEUE, RESULTS_QUEUE, "beat_processing_dlq"):
        ch.queue_purge(queue)
    yield ch
    connection.close()


def _publish_command(settings, body: bytes) -> None:
    connection = connect(settings.rabbitmq_url)
    ch = connection.channel()
    ch.confirm_delivery()
    ch.basic_publish(EXCHANGE, PROCESS_KEY, body, pika.BasicProperties(delivery_mode=2, message_id=str(uuid.uuid4())),
                     mandatory=True)
    connection.close()


def _consume_for(settings, storage, seconds: float) -> None:
    connection = connect(settings.rabbitmq_url)
    ch = connection.channel()
    ch.confirm_delivery()
    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(PROCESSING_QUEUE, lambda c, m, p, b: main.handle(c, m, p, b, settings, storage))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        connection.process_data_events(time_limit=0.2)
    connection.close()


def _command(beat_id: int, stems_key=None) -> bytes:
    return json.dumps({
        "event_id": str(uuid.uuid4()), "event_type": "beat.media.process", "occurred_at": "2026-11-02T10:00:00Z",
        "beat_id": beat_id, "producer_id": 1,
        "files": {"wav_key": f"raw/{beat_id}/master.wav", "cover_key": f"raw/{beat_id}/cover.jpg", "stems_key": stems_key},
        "options": {"voice_tag": True, "tag_interval_sec": 20},
    }).encode()


def test_command_produces_result_message(channel, settings, storage, beat_id, samples):
    storage.client.upload_file(samples["good_master.wav"], settings.bucket_temp, f"raw/{beat_id}/master.wav")
    storage.client.upload_file(samples["good_cover.jpg"], settings.bucket_temp, f"raw/{beat_id}/cover.jpg")
    _publish_command(settings, _command(beat_id))
    _consume_for(settings, storage, 8)

    method, _, body = channel.basic_get(RESULTS_QUEUE, auto_ack=True)
    assert method is not None
    result = json.loads(body)
    assert (result["beat_id"], result["result"]) == (beat_id, "processed")
    assert channel.queue_declare(PROCESSING_QUEUE, passive=True).method.message_count == 0  # acknowledged


def test_temporary_failure_three_retries_then_dlq(channel, settings, storage, beat_id, samples, monkeypatch):
    """Antivirus "down": 1 attempt + 3 retries via the delay queues, then beat_processing_dlq. No result is published."""
    storage.client.upload_file(samples["good_master.wav"], settings.bucket_temp, f"raw/{beat_id}/master.wav")
    storage.client.upload_file(samples["good_cover.jpg"], settings.bucket_temp, f"raw/{beat_id}/cover.jpg")
    storage.client.upload_file(samples["good_stems.zip"], settings.bucket_temp, f"raw/{beat_id}/stems.zip")
    down = dataclasses.replace(settings, antivirus_mode="unavailable")

    attempts = []
    real_process = main.process

    def counting(command, s, st):
        attempts.append(1)
        return real_process(command, s, st)

    monkeypatch.setattr(main, "process", counting)
    _publish_command(settings, _command(beat_id, stems_key=f"raw/{beat_id}/stems.zip"))
    _consume_for(down, storage, 6)

    assert len(attempts) == 4
    method, properties, _ = channel.basic_get("beat_processing_dlq", auto_ack=True)
    assert method is not None
    assert sum(d["count"] for d in properties.headers["x-death"] if d["reason"] == "expired") == 3
    assert channel.basic_get(RESULTS_QUEUE, auto_ack=True)[0] is None


def test_malformed_command_goes_to_dlq(channel, settings, storage):
    _publish_command(settings, b"{not json")
    _consume_for(settings, storage, 1)
    assert channel.basic_get("beat_processing_dlq", auto_ack=True)[0] is not None
