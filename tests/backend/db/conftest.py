"""Fixtures for the relational **parity** suite (v0.5 M21 slice 3).

The ``repository`` fixture is parametrized over *both* backends. The SQLite leg (Tier 0) always
runs, against a fresh temp-file database per test built by running the real Alembic chain to
``head`` — so the migration is exercised on every test, not just the one that asserts on it. The
PostgreSQL leg (Tier 1) runs only when ``XTALATE_TEST_DATABASE_URL`` points at a reachable server;
otherwise it **skips**, never fails — the same "parity is a test, skip when the service is absent"
contract the object-store suite uses. The Postgres leg upgrades then downgrades around each test so
a shared server is left clean.

To run the Postgres leg locally::

    XTALATE_TEST_DATABASE_URL=postgresql+psycopg://xtalate:xtalate@127.0.0.1:5432/xtalate \
    pytest tests/backend/db

The Tier 1 compose stack (M21 slice 4) wires exactly this variable so the leg runs in CI.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.db import Repository  # noqa: E402
from backend.db.engine import build_engine, build_sessionmaker  # noqa: E402

_PG_URL_ENV = "XTALATE_TEST_DATABASE_URL"
_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def _alembic_config(database_url: str) -> Config:
    """An Alembic config pointed at ``database_url`` via the ``-x db_url=`` override env.py uses."""
    config = Config(str(_ALEMBIC_INI))
    config.cmd_opts = type("_Opts", (), {"x": [f"db_url={database_url}"]})()  # get_x_argument
    return config


def _settings(database_url: str) -> Settings:
    return Settings(_env_file=None, database_url=database_url)  # type: ignore[call-arg]


@pytest.fixture(params=["sqlite", "postgresql"])
def repository(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Repository]:
    backend = request.param
    if backend == "sqlite":
        database_url = f"sqlite+pysqlite:///{tmp_path / 'parity.db'}"
        config = _alembic_config(database_url)
        command.upgrade(config, "head")
        # Build the engine explicitly so the fixture can dispose its pool on teardown (no leaked
        # SQLite connections warned about at GC); the Repository is the same either way.
        engine = build_engine(_settings(database_url))
        try:
            yield Repository(build_sessionmaker(engine))
        finally:
            engine.dispose()
        return

    pg_url = os.environ.get(_PG_URL_ENV)
    if not pg_url:
        pytest.skip(f"PostgreSQL leg not configured (set {_PG_URL_ENV} to run it against a server)")
    config = _alembic_config(pg_url)
    command.downgrade(config, "base")  # start from empty even if a prior run left tables
    command.upgrade(config, "head")
    engine = build_engine(_settings(pg_url))
    try:
        yield Repository(build_sessionmaker(engine))
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def unique_id(prefix: str) -> str:
    """A short unique primary key so a shared Postgres server never collides across tests."""
    return f"{prefix}-{uuid.uuid4().hex[:16]}"
