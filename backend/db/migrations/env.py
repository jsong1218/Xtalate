"""Alembic migration environment (v0.5 M21 slice 3).

The URL comes from the service settings, not ``alembic.ini`` — so ``alembic upgrade head`` migrates
whatever database the environment points at (SQLite in Tier 0, PostgreSQL in Tier 1) with no second
configuration surface and no credential in a tracked file. A caller may still override for a one-off
run via ``alembic -x db_url=…`` (used by the test suite to target a temp database).
``target_metadata`` is :data:`backend.db.base.Base.metadata`, so ``--autogenerate`` diffs the ORM.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.config import get_settings

# Import the models module for its side effect: registering every table on Base.metadata.
from backend.db import models  # noqa: F401
from backend.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the URL: an ``-x db_url=…`` override wins, else the service settings."""
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    if override:
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (``alembic upgrade --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch makes ALTERs work on SQLite too (its ALTER TABLE is limited) — future
        # migrations that alter columns then behave the same on both backends.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
