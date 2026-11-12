"""signature_otps.created_at for the limits of NFR-31 (ADR 0007, GAP-70).

Revision ID: 0003
"""

from migrations.sqlfile import run_sql_file

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql_file("0003_signature_otps_created_at.sql")


def downgrade() -> None:
    raise NotImplementedError("Recreate the database instead")
