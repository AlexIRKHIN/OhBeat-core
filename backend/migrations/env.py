"""Alembic environment. Migrations run under the schema owner, not under the application role."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def database_url() -> str:
    # Tests pass the URL of a temporary database through the config
    return config.get_main_option("sqlalchemy.url") or os.environ["MIGRATIONS_DATABASE_URL"]


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline mode is not used: migrations are plain SQL files in migrations/sql")

run_migrations_online()
