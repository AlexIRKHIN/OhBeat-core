"""The reference schema: migration 0001 must give exactly 05_Database/schema.sql (ADR 0002),
and the application role must not be able to change the Audit Log (NFR-32)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from tests.conftest import OWNER_URL, migrate, recreate_database
from tests.schema_fingerprint import fingerprint

SQL_DIR = Path(__file__).parent.parent / "migrations" / "sql"
SPEC_SCHEMA = Path("/spec/05_Database/schema.sql")


def _read_normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.mark.skipif(not SPEC_SCHEMA.exists(), reason="documentation repository is not mounted at /spec")
def test_migration_sql_is_unchanged_copy_of_spec_schema():
    assert _read_normalized(SQL_DIR / "0001_schema.sql") == _read_normalized(SPEC_SCHEMA)


def test_migration_0001_equals_reference_schema():
    """Database A: schema.sql and the GRANTs from its header applied directly.
    Database B: `alembic upgrade 0001`. Their catalogs must match."""
    reference_sql = _read_normalized(SPEC_SCHEMA if SPEC_SCHEMA.exists() else SQL_DIR / "0001_schema.sql")
    grants_sql = _read_normalized(SQL_DIR / "0001_grants.sql")

    recreate_database("ohbeat_schema_ref")
    ref_engine = create_engine(OWNER_URL.set(database="ohbeat_schema_ref"))
    with ref_engine.begin() as conn:
        conn.connection.driver_connection.execute(reference_sql)
        conn.connection.driver_connection.execute(grants_sql)

    recreate_database("ohbeat_schema_mig")
    migrate("ohbeat_schema_mig", "0001")
    mig_engine = create_engine(OWNER_URL.set(database="ohbeat_schema_mig"))

    with ref_engine.connect() as ref, mig_engine.connect() as mig:
        expected, actual = fingerprint(ref), fingerprint(mig)
    ref_engine.dispose()
    mig_engine.dispose()

    assert expected["columns"], "reference schema produced no tables"
    for part in expected:
        assert actual[part] == expected[part], f"migration 0001 differs from schema.sql in {part}"


def test_schema_has_21_reference_tables_plus_extensions(owner_engine):
    with owner_engine.connect() as conn:
        tables = set(
            conn.scalars(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        )
    extensions = {"refresh_tokens", "login_attempts", "alembic_version"}  # ADR 0007
    assert extensions <= tables
    assert len(tables - extensions) == 21


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
def test_nfr32_app_role_cannot_change_audit_log(app_engine, statement):
    with app_engine.begin() as conn:
        conn.execute(text("INSERT INTO audit_log (action, entity) VALUES ('test.insert', 'test')"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        with app_engine.begin() as conn:
            conn.execute(text(statement))


def test_nfr32_app_role_can_append_and_read_audit_log(app_engine):
    with app_engine.begin() as conn:
        conn.execute(text("INSERT INTO audit_log (action, entity) VALUES ('test.insert', 'test')"))
        assert conn.scalar(text("SELECT count(*) FROM audit_log WHERE action = 'test.insert'")) == 1


def test_app_role_has_no_access_to_alembic_version(app_engine):
    with pytest.raises(ProgrammingError, match="permission denied"):
        with app_engine.connect() as conn:
            conn.execute(text("SELECT * FROM alembic_version"))


def test_gap2_one_contract_per_order_item(owner_engine):
    with owner_engine.connect() as conn:
        definition = conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'contracts_order_item_id_key'"
            )
        )
    assert definition == "UNIQUE (order_item_id)"
