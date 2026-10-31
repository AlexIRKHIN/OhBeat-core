"""Database connection.

The schema is created only by migrations (ADR 0002); ORM models just describe
existing tables and never create them.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """One session per HTTP request. Services call commit() themselves;
    anything not committed is rolled back when the session closes."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
