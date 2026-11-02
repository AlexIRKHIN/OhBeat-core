"""S3 (MinIO) for the worker: download sources, put results under deterministic keys."""

import hashlib

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from worker.config import Settings
from worker.errors import RejectError, TransientError

IMMUTABLE = "public, max-age=31536000, immutable"  # RFC_Audio_Streaming.md §2 p.2


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def download_source(self, key: str, path: str) -> None:
        """A missing source is a business result (lifecycle removed it), any other failure is temporary."""
        try:
            self.client.download_file(self.settings.bucket_temp, key, path)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                # ASSUMPTION: GAP-22 — sources are removed by the 24-hour lifecycle rule
                raise RejectError("SOURCE_FILES_EXPIRED", "Исходные файлы удалены по сроку хранения, загрузите бит заново") from None
            raise TransientError(f"S3 download failed: {exc}") from exc
        except BotoCoreError as exc:
            raise TransientError(f"S3 is unavailable: {exc}") from exc

    def put_file(self, bucket: str, key: str, path: str, content_type: str, sha256: str, cache_control: str | None = None) -> None:
        """Uploads a result. The SHA-256 goes to object metadata: Core API reads it with HeadObject (GAP-50)."""
        extra = {"ContentType": content_type, "Metadata": {"sha256": sha256}}
        if cache_control:
            extra["CacheControl"] = cache_control
        try:
            self.client.upload_file(path, bucket, key, ExtraArgs=extra)
        except (ClientError, BotoCoreError) as exc:
            raise TransientError(f"S3 upload failed: {exc}") from exc
