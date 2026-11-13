"""SQLAlchemy engine and session factory, built from settings.DATABASE_URL."""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=4)
def get_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(settings.DATABASE_URL), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
