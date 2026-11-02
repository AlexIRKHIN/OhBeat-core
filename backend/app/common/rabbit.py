"""RabbitMQ: connection and topology (RabbitMQ_Worker.md §1, §5; slice-1-plan.md §5).

Exchanges and queues are declared by both sides (Core API and Media Worker) with identical
arguments: a declaration is idempotent, so whoever starts first creates them.

    media.events (direct)  -- beat.media.process   --> beat_processing_queue  (consumer: Media Worker)
                           -- beat.media.processed --> beat_results_queue     (consumer: Core API)
    media.retry  (direct)  -- <key>.30s / .2m / .10m --> delay queues; after the TTL a message
                              goes back to media.events with its original routing key
    media.dlx    (direct)  -- <queue>_dlq --> beat_processing_dlq / beat_results_dlq

Keep in sync with worker/worker/rabbit.py.
"""

import pika
from pika.adapters.blocking_connection import BlockingChannel

from app.common.config import get_settings

EXCHANGE = "media.events"
RETRY_EXCHANGE = "media.retry"
DLX_EXCHANGE = "media.dlx"

PROCESS_KEY = "beat.media.process"
PROCESSED_KEY = "beat.media.processed"
PROCESSING_QUEUE = "beat_processing_queue"
RESULTS_QUEUE = "beat_results_queue"

# Delay before the 1st, 2nd and 3rd retry (RabbitMQ_Worker.md §5)
RETRY_DELAYS = (("30s", 30_000), ("2m", 120_000), ("10m", 600_000))


def connect() -> pika.BlockingConnection:
    params = pika.URLParameters(get_settings().rabbitmq_url)
    params.heartbeat = 30
    params.blocked_connection_timeout = 30
    return pika.BlockingConnection(params)


def _declare_flow(channel: BlockingChannel, queue: str, routing_key: str, retry_delays: tuple) -> None:
    dlq = f"{queue.removesuffix('_queue')}_dlq"
    channel.queue_declare(
        queue=queue,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX_EXCHANGE, "x-dead-letter-routing-key": dlq},
    )
    channel.queue_bind(queue=queue, exchange=EXCHANGE, routing_key=routing_key)

    for suffix, ttl_ms in retry_delays:
        delay_queue = f"{queue.removesuffix('_queue')}_delay_{suffix}"
        channel.queue_declare(
            queue=delay_queue,
            durable=True,
            arguments={
                "x-message-ttl": ttl_ms,
                "x-dead-letter-exchange": EXCHANGE,
                "x-dead-letter-routing-key": routing_key,
            },
        )
        channel.queue_bind(queue=delay_queue, exchange=RETRY_EXCHANGE, routing_key=f"{routing_key}.{suffix}")

    channel.queue_declare(queue=dlq, durable=True)
    channel.queue_bind(queue=dlq, exchange=DLX_EXCHANGE, routing_key=dlq)


def declare_topology(channel: BlockingChannel, retry_delays: tuple = RETRY_DELAYS) -> None:
    for name in (EXCHANGE, RETRY_EXCHANGE, DLX_EXCHANGE):
        channel.exchange_declare(exchange=name, exchange_type="direct", durable=True)
    _declare_flow(channel, PROCESSING_QUEUE, PROCESS_KEY, retry_delays)
    _declare_flow(channel, RESULTS_QUEUE, PROCESSED_KEY, retry_delays)
