"""Object storage (S3 / MinIO) behind a small interface, so tests and other modules
do not depend on boto3 details.

Two clients are used on purpose:
* `internal` talks to MinIO inside the docker network (http://minio:9000);
* `signer` only signs links for the address the browser sees (http://localhost:9000).
  A signature covers the host, so a link signed for "minio:9000" would not open in the browser.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import BotoCoreError, ClientError

from app.common.config import get_settings


class StorageUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    content_type: str | None


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]


class ObjectStorage(Protocol):
    def presigned_post(
        self, bucket: str, key: str, content_type: str, max_bytes: int, expires_seconds: int
    ) -> PresignedPost: ...

    def head(self, bucket: str, key: str) -> ObjectInfo | None: ...

    def read(self, bucket: str, key: str, max_bytes: int) -> bytes: ...

    def put(self, bucket: str, key: str, data: bytes, content_type: str, cache_control: str | None = None) -> None: ...

    def public_url(self, key: str) -> str: ...


def _client(endpoint: str) -> BaseClient:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )


class S3Storage:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._internal = _client(settings.s3_internal_endpoint)
        self._signer = _client(settings.s3_public_endpoint)

    def presigned_post(
        self, bucket: str, key: str, content_type: str, max_bytes: int, expires_seconds: int
    ) -> PresignedPost:
        # content-length-range makes S3 itself reject a bigger file (REST API §2.1)
        result = self._signer.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires_seconds,
        )
        return PresignedPost(url=result["url"], fields=result["fields"])

    def head(self, bucket: str, key: str) -> ObjectInfo | None:
        try:
            meta = self._internal.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise StorageUnavailable from exc
        except BotoCoreError as exc:
            raise StorageUnavailable from exc
        return ObjectInfo(size_bytes=meta["ContentLength"], content_type=meta.get("ContentType"))

    def read(self, bucket: str, key: str, max_bytes: int) -> bytes:
        try:
            body = self._internal.get_object(Bucket=bucket, Key=key)["Body"]
            return body.read(max_bytes + 1)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailable from exc

    def put(self, bucket: str, key: str, data: bytes, content_type: str, cache_control: str | None = None) -> None:
        extra = {"ContentType": content_type}
        if cache_control:
            extra["CacheControl"] = cache_control
        try:
            self._internal.put_object(Bucket=bucket, Key=key, Body=data, **extra)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailable from exc

    def public_url(self, key: str) -> str:
        """Address of an object in the public bucket (MinIO plays the role of CDN locally)."""
        return f"{self._settings.s3_public_endpoint.rstrip('/')}/{self._settings.bucket_public}/{key}"


@lru_cache
def get_storage() -> ObjectStorage:
    return S3Storage()
