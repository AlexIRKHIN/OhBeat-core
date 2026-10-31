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


@pytest.fixture(autouse=True)
def clean_tables(owner_engine):
    """Every test starts with no users. TRUNCATE ... CASCADE also empties every table
    that references users. It runs under the owner: the application role may not TRUNCATE audit_log."""
    with owner_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, login_attempts RESTART IDENTITY CASCADE"))
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
