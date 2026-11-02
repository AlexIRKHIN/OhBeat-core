"""Test environment: a separate database `ohbeat_test` on the same PostgreSQL,
real MinIO, migrations applied from scratch once per test session.

Run inside the api container:  docker compose exec api pytest
"""

import os

from sqlalchemy.engine import make_url

# --- Point the application at the test database BEFORE app modules are imported ---
OWNER_URL = make_url(os.environ["MIGRATIONS_DATABASE_URL"])
APP_URL = make_url(os.environ["DATABASE_URL"])
TEST_DB = "ohbeat_test"
TEST_OWNER_URL = OWNER_URL.set(database=TEST_DB)
TEST_APP_URL = APP_URL.set(database=TEST_DB)

os.environ["DATABASE_URL"] = TEST_APP_URL.render_as_string(hide_password=False)
# Inside docker the browser address localhost:9000 is unreachable; tests upload through the internal one
os.environ["S3_PUBLIC_ENDPOINT"] = os.environ.get("S3_INTERNAL_ENDPOINT", "http://minio:9000")

# Own buckets: ids restart from 1 in every test, so shared buckets would mix objects of different beats
TEST_BUCKETS = {"BUCKET_TEMP": "test-temp-uploads", "BUCKET_PRIVATE": "test-private-media", "BUCKET_PUBLIC": "test-public-media"}
os.environ.update(TEST_BUCKETS)

# A separate RabbitMQ virtual host: tests never touch the queues of the running environment
RABBIT_URL = make_url(os.environ["RABBITMQ_URL"].replace("amqp://", "postgresql://", 1))  # reuse the URL parser
TEST_VHOST = "ohbeat_test"
# Retries after 0.2 s instead of 30 s / 2 min / 10 min, so tests can watch the whole path to the DLQ
os.environ["RABBIT_RETRY_DELAYS_MS"] = "200,200,200"
os.environ["RABBITMQ_URL"] = (
    f"amqp://{RABBIT_URL.username}:{RABBIT_URL.password}@{RABBIT_URL.host}:{RABBIT_URL.port or 5672}/{TEST_VHOST}"
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from seeds.run import seed_dictionaries  # noqa: E402


def recreate_database(name: str) -> None:
    """DROP + CREATE under the schema owner (it has CREATEDB, see infra/postgres/init-roles.sh)."""
    admin = create_engine(OWNER_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()


def migrate(database: str, revision: str = "head") -> None:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    cfg.set_main_option("sqlalchemy.url", OWNER_URL.set(database=database).render_as_string(hide_password=False))
    command.upgrade(cfg, revision)


@pytest.fixture(scope="session")
def owner_engine():
    recreate_database(TEST_DB)
    migrate(TEST_DB)
    engine = create_engine(TEST_OWNER_URL)
    with engine.begin() as conn:
        seed_dictionaries(conn)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def test_buckets():
    """Creates the test buckets; the public one is readable anonymously, like public-media."""
    import json

    from app.common.config import get_settings
    from app.common.storage import _client

    s3 = _client(get_settings().s3_internal_endpoint)
    for bucket in TEST_BUCKETS.values():
        try:
            s3.head_bucket(Bucket=bucket)
        except Exception:
            s3.create_bucket(Bucket=bucket)
    s3.put_bucket_policy(Bucket=TEST_BUCKETS["BUCKET_PUBLIC"], Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]}, "Action": ["s3:GetObject"],
                       "Resource": [f"arn:aws:s3:::{TEST_BUCKETS['BUCKET_PUBLIC']}/*"]}],
    }))
    return s3


@pytest.fixture(autouse=True)
def clean_buckets(test_buckets):
    for bucket in TEST_BUCKETS.values():
        for page in test_buckets.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                test_buckets.delete_object(Bucket=bucket, Key=obj["Key"])
    yield


@pytest.fixture(autouse=True)
def clean_tables(owner_engine):
    """Every test starts with no users. TRUNCATE ... CASCADE also empties every table
    that references users. It runs under the owner: the application role may not TRUNCATE audit_log."""
    with owner_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, login_attempts, outbox RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client(owner_engine):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def app_engine(owner_engine):
    """Connection under the application login (member of ohbeat_app) — for privilege tests."""
    engine = create_engine(TEST_APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def rabbit_vhost():
    """Recreates the test virtual host through the RabbitMQ management API: queues from a previous
    run (maybe with other delays) are dropped together with it."""
    auth = (RABBIT_URL.username, RABBIT_URL.password)
    base = os.environ.get("RABBITMQ_MANAGEMENT_URL", "http://rabbitmq:15672")
    httpx.delete(f"{base}/api/vhosts/{TEST_VHOST}", auth=auth)
    httpx.put(f"{base}/api/vhosts/{TEST_VHOST}", auth=auth).raise_for_status()
    httpx.put(
        f"{base}/api/permissions/{TEST_VHOST}/{RABBIT_URL.username}",
        json={"configure": ".*", "write": ".*", "read": ".*"},
        auth=auth,
    ).raise_for_status()
    return TEST_VHOST


@pytest.fixture
def rabbit_channel(rabbit_vhost):
    """A channel in the test vhost with the topology declared and the main queues empty."""
    from app.common.rabbit import PROCESSING_QUEUE, RESULTS_QUEUE, connect, declare_topology

    connection = connect()
    channel = connection.channel()
    declare_topology(channel)
    for queue in (PROCESSING_QUEUE, RESULTS_QUEUE):
        channel.queue_purge(queue)
    yield channel
    connection.close()
