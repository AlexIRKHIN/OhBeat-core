"""Additions to the reference schema (ADR 0007): refresh tokens, login attempts, indexes.

Revision ID: 0002
"""

from migrations.sqlfile import run_sql_file

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0002_extensions.sql")


def downgrade() -> None:
    raise NotImplementedError("Recreate the database instead")
