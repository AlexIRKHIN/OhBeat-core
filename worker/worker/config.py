"""Settings of Media Worker, from environment variables.

The worker has no access to the Core API database (RabbitMQ_Worker.md, intro):
it only reads the queue, works with S3 and publishes results.
"""

import os
from dataclasses import dataclass, field


def _delays() -> tuple[tuple[str, int], ...]:
    # Delay before the 1st, 2nd and 3rd retry (RabbitMQ_Worker.md §5). Tests shorten them.
    raw = os.environ.get("RABBIT_RETRY_DELAYS_MS", "30000,120000,600000")
    values = [int(v) for v in raw.split(",")]
    return tuple(zip(("30s", "2m", "10m"), values))


@dataclass(frozen=True)
class Settings:
    rabbitmq_url: str = field(default_factory=lambda: os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F"))
    retry_delays: tuple = field(default_factory=_delays)

    s3_endpoint: str = field(default_factory=lambda: os.environ.get("S3_INTERNAL_ENDPOINT", "http://minio:9000"))
    s3_access_key: str = field(default_factory=lambda: os.environ["S3_ACCESS_KEY"])
    s3_secret_key: str = field(default_factory=lambda: os.environ["S3_SECRET_KEY"])
    bucket_temp: str = "temp-uploads"
    bucket_private: str = "private-media"
    bucket_public: str = "public-media"

    # normal | unavailable — the mock antivirus can pretend to be down (ADR 0006)
    antivirus_mode: str = field(default_factory=lambda: os.environ.get("ANTIVIRUS_MODE", "normal"))
    voice_tag_path: str = field(default_factory=lambda: os.environ.get("VOICE_TAG_PATH", "/opt/ohbeat/voice_tag.wav"))
    work_dir: str = field(default_factory=lambda: os.environ.get("WORKER_TMP", "/tmp/ohbeat-worker"))


def get_settings() -> Settings:
    return Settings()
