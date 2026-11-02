"""Settings of Core API. Values come from environment variables (.env in docker compose)."""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Connection of the application: login user that is a member of ohbeat_app (GAP-5)
    database_url: str

    # S3 (MinIO). The internal endpoint is used by Core API itself;
    # the public one is the host the browser sees, presigned links are signed for it.
    s3_internal_endpoint: str = "http://minio:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str
    s3_secret_key: str
    s3_region: str = "us-east-1"
    bucket_temp: str = "temp-uploads"
    bucket_private: str = "private-media"
    bucket_public: str = "public-media"
    presigned_ttl_seconds: int = 3600  # FR-6: upload forms live 1 hour

    # Auth (REST API §2.8)
    jwt_secret: str
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_days: int = 30  # ASSUMPTION: GAP-11
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Platform settings (ASSUMPTION: GAP-10)
    platform_fee_percent: Decimal = Decimal("10")
    voice_tag_interval_sec: int = 20

    # RabbitMQ (outbox relay, consumer of processing results)
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/%2F"
    relay_interval_seconds: float = 1.0  # RabbitMQ_Worker.md §2: once a second
    relay_batch_size: int = 100
    # Delay before the 1st, 2nd and 3rd retry, ms (RabbitMQ_Worker.md §5). Tests shorten them.
    rabbit_retry_delays_ms: str = "30000,120000,600000"

    # FR-8: beats left in `uploading` are deleted after this many hours
    upload_ttl_hours: int = 24

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
