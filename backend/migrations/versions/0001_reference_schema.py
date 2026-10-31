"""Reference schema: an unchanged copy of 05_Database/schema.sql plus its privileges.

Revision ID: 0001
"""

from migrations.sqlfile import run_sql_file

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0001_schema.sql")
    run_sql_file("0001_grants.sql")


def downgrade() -> None:
    raise NotImplementedError("The reference schema is not rolled back; recreate the database instead")
