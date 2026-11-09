"""Alembic environment: reads DATABASE_URL from app settings and targets Base.metadata."""
from logging.config import fileConfig

from alembic import context
from app.core.config import settings
from app.db import models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base, get_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = get_engine(settings.DATABASE_URL)
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            # SQLite rebuilds a table for batch changes (drop + copy). With foreign keys enforced,
            # rebuilding a parent such as loan_accounts fails while payments still references it.
            # The pragma is a no-op inside a transaction, so it is set before migrations begin.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            # The pragma opened a transaction. Commit it, or Alembic (which does not own that
            # transaction) would roll back every migration when the connection closes.
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
