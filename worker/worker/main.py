"""Media Worker: consumer of beat_processing_queue (RabbitMQ_Worker.md §1, §5).

For every command:
* checks passed or failed -> publish the result (processed / rejected), then ACK the command;
* temporary or unexpected failure -> retry: a copy goes to the delay queue for 30 s, 2 min or 10 min
  (the attempt number comes from x-death), then ACK the original (ASSUMPTION: GAP-51);
* after the 3rd retry -> NACK without requeue, the broker moves the message to beat_processing_dlq.

The command is acknowledged only after the result is confirmed by the broker: if the worker dies
in between, the command is delivered again and processed again over the same keys (idempotency).

Run:  python -m worker.main
"""

import json
import logging
import time

import pika
from pika.exceptions import AMQPError

from worker.config import Settings, get_settings
from worker.processor import process
from worker.rabbit import (
    EXCHANGE,
    MAX_RETRIES,
    PROCESS_KEY,
    PROCESSED_KEY,
    PROCESSING_QUEUE,
    RETRY_EXCHANGE,
    connect,
    declare_topology,
    retries_so_far,
)
from worker.storage import Storage

log = logging.getLogger("worker")


def publish_result(channel, result: dict) -> None:
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=PROCESSED_KEY,
        body=json.dumps(result, ensure_ascii=False).encode(),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=result["event_id"],
            type=result["event_type"],
        ),
        mandatory=True,
    )


def schedule_retry(channel, settings: Settings, properties, body: bytes) -> bool:
    """Returns False when retries are exhausted and the message must go to the DLQ."""
    done = retries_so_far(properties)
    if done >= MAX_RETRIES:
        return False
    suffix, delay_ms = settings.retry_delays[done]
    channel.basic_publish(
        exchange=RETRY_EXCHANGE,
        routing_key=f"{PROCESS_KEY}.{suffix}",
        body=body,
        # Headers are copied: x-death of the previous delays keeps counting the attempts
        properties=pika.BasicProperties(
            content_type=properties.content_type,
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=properties.message_id,
            type=properties.type,
            headers=properties.headers,
        ),
        mandatory=True,
    )
    log.warning("retry %s of %s scheduled in %s ms", done + 1, MAX_RETRIES, delay_ms)
    return True


def handle(channel, method, properties, body: bytes, settings: Settings, storage: Storage) -> None:
    try:
        command = json.loads(body)
        beat_id = command["beat_id"]
    except (ValueError, KeyError, TypeError):
        # A broken message will never succeed: straight to the DLQ
        log.error("ALERT: malformed command %s moved to DLQ", properties.message_id)
        channel.basic_nack(method.delivery_tag, requeue=False)
        return

    log.info("beat %s: processing started (attempt %s)", beat_id, retries_so_far(properties) + 1)
    try:
        result = process(command, settings, storage)
    except Exception as exc:  # TransientError, FfmpegError or anything unexpected
        log.warning("beat %s: temporary failure: %s", beat_id, exc)
        if schedule_retry(channel, settings, properties, body):
            channel.basic_ack(method.delivery_tag)
        else:
            # "Alert to the on-duty engineer": an ERROR line in the log (GAP-21)
            log.error("ALERT: beat %s moved to DLQ after %s retries", beat_id, MAX_RETRIES)
            channel.basic_nack(method.delivery_tag, requeue=False)
        return

    publish_result(channel, result)  # waits for the publisher confirm
    channel.basic_ack(method.delivery_tag)
    log.info("beat %s: result %s published", beat_id, result["result"])


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("pika").setLevel(logging.CRITICAL)
    settings = get_settings()
    storage = Storage(settings)
    while True:
        try:
            connection = connect(settings.rabbitmq_url)
            channel = connection.channel()
            channel.confirm_delivery()
            declare_topology(channel, settings.retry_delays)
            channel.basic_qos(prefetch_count=1)  # one beat at a time: FFmpeg is heavy
            channel.basic_consume(
                PROCESSING_QUEUE,
                lambda ch, m, p, b: handle(ch, m, p, b, settings, storage),
            )
            log.info("waiting for commands in %s (antivirus: %s)", PROCESSING_QUEUE, settings.antivirus_mode)
            channel.start_consuming()
        except AMQPError as exc:
            log.warning("RabbitMQ is unavailable (%s), reconnecting in 5 s", exc.__class__.__name__)
            time.sleep(5)


if __name__ == "__main__":
    run_forever()

