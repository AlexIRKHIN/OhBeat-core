"""Helper for migrations written in plain SQL (ADR 0002)."""

from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).parent / "sql"


def run_sql_file(name: str) -> None:
    """Execute a whole .sql file as one batch.

    The driver connection is used directly: SQLAlchemy's text() would treat
    "name:" fragments as bind parameters, and the file must run exactly as written.
    """
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    op.get_bind().connection.driver_connection.execute(sql)
