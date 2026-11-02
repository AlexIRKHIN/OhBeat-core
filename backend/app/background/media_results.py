"""Consumer of beat_results_queue: Core API applies processing results (FR-12).

Retries and the DLQ work the same way as in Media Worker (GAP-20, GAP-51):
a temporary failure (database or S3 down) -> copy to a delay queue 30 s / 2 min / 10 min + ACK;
after the 3rd retry -> NACK, the broker moves the message to beat_results_dlq.

Run:  python -m app.background.media_results
"""

import json
import logging
import time

import pika
from pika.exceptions import AMQPError

from app.catalog.media_results import apply_result
from app.common.db import get_session_factory
from app.common.rabbit import (
    MAX_RETRIES,
    PROCESSED_KEY,
    RESULTS_QUEUE,
    RETRY_EXCHANGE,
    connect,
    declare_topology,
    retries_so_far,
    retry_delays,
)
from app.common.storage import get_storage
from app.notifications.service import get_notifier

log = logging.getLogger("media-results")


def _schedule_retry(channel, properties, body: bytes) -> bool:
    done = retries_so_far(properties)
    if done >= MAX_RETRIES:
        return False
    suffix, delay_ms = retry_delays()[done]
    channel.basic_publish(
        exchange=RETRY_EXCHANGE,
        routing_key=f"{PROCESSED_KEY}.{suffix}",
        body=body,
        properties=pika.BasicProperties(
            content_type=properties.content_type,
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=properties.message_id,
            type=properties.type,
            headers=properties.headers,  # x-death keeps counting the attempts
        ),
        mandatory=True,
    )
    log.warning("retry %s of %s scheduled in %s ms", done + 1, MAX_RETRIES, delay_ms)
    return True


def handle(channel, method, properties, body: bytes) -> None:
    try:
        message = json.loads(body)
        int(message["beat_id"])
        message["result"]
    except (ValueError, KeyError, TypeError):
        log.error("ALERT: malformed result %s moved to DLQ", properties.message_id)
        channel.basic_nack(method.delivery_tag, requeue=False)
        return

    try:
        with get_session_factory()() as db:
            apply_result(db, get_storage(), get_notifier(), message)
    except Exception as exc:  # database or S3 unavailable, output not found, anything unexpected
        log.warning("beat %s: result not applied: %s", message["beat_id"], exc)
        if _schedule_retry(channel, properties, body):
            channel.basic_ack(method.delivery_tag)
        else:
            log.error("ALERT: result for beat %s moved to DLQ after %s retries", message["beat_id"], MAX_RETRIES)
            channel.basic_nack(method.delivery_tag, requeue=False)
        return
    channel.basic_ack(method.delivery_tag)


def run_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("pika").setLevel(logging.CRITICAL)
    while True:
        try:
            connection = connect()
            channel = connection.channel()
            channel.confirm_delivery()
            declare_topology(channel)
            channel.basic_qos(prefetch_count=10)
            channel.basic_consume(RESULTS_QUEUE, handle)
            log.info("waiting for results in %s", RESULTS_QUEUE)
            channel.start_consuming()
        except AMQPError as exc:
            log.warning("RabbitMQ is unavailable (%s), reconnecting in 5 s", exc.__class__.__name__)
            time.sleep(5)


if __name__ == "__main__":
    run_forever()
