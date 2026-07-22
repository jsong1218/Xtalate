"""The Alembic chain builds the schema from empty (v0.5 M21 slice 3).

``alembic upgrade head`` on a fresh database must create all four tables; ``downgrade base`` must
remove them; and — the guard against the classic drift bug — ``alembic check`` must report *no*
pending autogenerate diff, i.e. the migration and the ORM models agree. These run on SQLite
unconditionally; the parity fixture already runs the upgrade against Postgres when configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402

from backend.db.base import Base  # noqa: E402

from .conftest import _alembic_config  # noqa: E402

_EXPECTED_TABLES = {"uploads", "jobs", "conversions", "reports"}


def _url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}"


def test_upgrade_head_creates_all_tables(tmp_path: Path) -> None:
    database_url = _url(tmp_path)
    command.upgrade(_alembic_config(database_url), "head")

    engine = sa.create_engine(database_url)
    tables = set(sa.inspect(engine).get_table_names())
    assert _EXPECTED_TABLES <= tables
    engine.dispose()


def test_downgrade_base_removes_all_tables(tmp_path: Path) -> None:
    database_url = _url(tmp_path)
    config: Config = _alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = sa.create_engine(database_url)
    tables = set(sa.inspect(engine).get_table_names())
    assert _EXPECTED_TABLES.isdisjoint(tables)
    engine.dispose()


def test_migration_matches_models_no_pending_diff(tmp_path: Path) -> None:
    """The migration is not stale: autogenerate against the upgraded DB yields no operations."""
    database_url = _url(tmp_path)
    command.upgrade(_alembic_config(database_url), "head")

    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"render_as_batch": True})
        diff = compare_metadata(context, Base.metadata)
    engine.dispose()

    assert diff == [], f"models drifted from the migration: {diff}"


def test_source_file_fk_is_set_null(tmp_path: Path) -> None:
    """Assert the reports-outlive-bytes rule at the DDL level, not just behaviorally."""
    database_url = _url(tmp_path)
    command.upgrade(_alembic_config(database_url), "head")

    engine = sa.create_engine(database_url)
    fks = sa.inspect(engine).get_foreign_keys("conversions")
    engine.dispose()

    by_col = {fk["constrained_columns"][0]: fk for fk in fks}
    assert by_col["source_file_id"]["options"]["ondelete"].upper() == "SET NULL"
    assert by_col["job_id"]["options"]["ondelete"].upper() == "CASCADE"
