"""RabbitMQ topology — the same as backend/app/common/rabbit.py (keep in sync).

    media.events (direct)  -- beat.media.process   --> beat_processing_queue  (consumer: this worker)
                           -- beat.media.processed --> beat_results_queue     (consumer: Core API)
    media.retry  (direct)  -- <key>.30s / .2m / .10m --> delay queues, back to media.events after the TTL
    media.dlx    (direct)  -- <queue>_dlq --> beat_processing_dlq / beat_results_dlq
"""

import pika

EXCHANGE = "media.events"
RETRY_EXCHANGE = "media.retry"
DLX_EXCHANGE = "media.dlx"

PROCESS_KEY = "beat.media.process"
PROCESSED_KEY = "beat.media.processed"
PROCESSING_QUEUE = "beat_processing_queue"
RESULTS_QUEUE = "beat_results_queue"
MAX_RETRIES = 3  # "no more than 3 retries after the first attempt"


def connect(url: str) -> pika.BlockingConnection:
    params = pika.URLParameters(url)
    params.heartbeat = 600  # long FFmpeg jobs must not look like a dead connection
    params.blocked_connection_timeout = 30
    return pika.BlockingConnection(params)


def _declare_flow(channel, queue: str, routing_key: str, retry_delays) -> None:
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


def declare_topology(channel, retry_delays) -> None:
    for name in (EXCHANGE, RETRY_EXCHANGE, DLX_EXCHANGE):
        channel.exchange_declare(exchange=name, exchange_type="direct", durable=True)
    _declare_flow(channel, PROCESSING_QUEUE, PROCESS_KEY, retry_delays)
    _declare_flow(channel, RESULTS_QUEUE, PROCESSED_KEY, retry_delays)


def retries_so_far(properties: pika.BasicProperties) -> int:
    """How many times the message already went through the delay queues.

    RabbitMQ writes an `x-death` header entry each time a message expires in a delay queue
    (RabbitMQ_Worker.md §5: "the attempt number comes from x-death").
    """
    deaths = (properties.headers or {}).get("x-death") or []
    return sum(int(d.get("count", 0)) for d in deaths if d.get("reason") == "expired")
