"""Tests of Media Worker: real FFmpeg, real MinIO, RabbitMQ in its own virtual host.

Run:  docker compose exec media-worker pytest
"""

import os
import random
from urllib.parse import urlparse

TEST_VHOST = "ohbeat_worker_test"
_url = urlparse(os.environ["RABBITMQ_URL"])
os.environ["RABBITMQ_URL"] = f"amqp://{_url.username}:{_url.password}@{_url.hostname}:{_url.port or 5672}/{TEST_VHOST}"
os.environ["RABBIT_RETRY_DELAYS_MS"] = "200,200,200"  # instead of 30 s / 2 min / 10 min

import httpx  # noqa: E402
import pytest  # noqa: E402

from worker.config import get_settings  # noqa: E402
from worker.samples import generate  # noqa: E402
from worker.storage import Storage  # noqa: E402


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, str]:
    """All sample files, generated once per test session: name -> path."""
    paths = generate(str(tmp_path_factory.mktemp("samples")))
    return {os.path.basename(p): p for p in paths}


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def storage(settings):
    return Storage(settings)


@pytest.fixture
def beat_id(storage, settings):
    """A random high id, so test objects never collide with real beats; removed after the test."""
    value = random.randint(900_000_000, 999_999_999)
    yield value
    s3 = storage.client
    for bucket, prefix in (
        (settings.bucket_temp, f"raw/{value}/"),
        (settings.bucket_private, f"beats/{value}/"),
        (settings.bucket_public, f"previews/{value}_"),
        (settings.bucket_public, f"covers/{value}_"),
    ):
        for obj in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])


@pytest.fixture(scope="session")
def rabbit_vhost():
    """Recreated per session through the management API (old queues with other delays are dropped)."""
    auth = (_url.username, _url.password)
    base = os.environ.get("RABBITMQ_MANAGEMENT_URL", "http://rabbitmq:15672")
    httpx.delete(f"{base}/api/vhosts/{TEST_VHOST}", auth=auth)
    httpx.put(f"{base}/api/vhosts/{TEST_VHOST}", auth=auth).raise_for_status()
    httpx.put(f"{base}/api/permissions/{TEST_VHOST}/{_url.username}",
              json={"configure": ".*", "write": ".*", "read": ".*"}, auth=auth).raise_for_status()
    return TEST_VHOST
