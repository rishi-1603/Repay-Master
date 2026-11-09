"""SQLAlchemy engine, session factory and declarative base.

DATABASE_URL selects the backend: sqlite (default, local) or postgresql+psycopg
(production). Schema changes go through Alembic migrations (backend/alembic), not
create_all, so the same migrations run on both.
"""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine(url: str | None = None):
    url = url or settings.DATABASE_URL
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


def session_factory(url: str | None = None) -> sessionmaker:
    return sessionmaker(bind=get_engine(url), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
