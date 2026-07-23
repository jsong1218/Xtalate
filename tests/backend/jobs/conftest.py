"""Fixtures for the job-core suite: a migrated SQLite repo, a filesystem store, the registry.

Deliberately self-contained — small inline POSCAR/XYZ samples rather than a dependency on the golden
corpus layout — so these tests exercise the *runner* (parse → convert → persist) without coupling to
another suite's fixtures. The database is built by running the Alembic chain to ``head`` (as the
parity suite does), so migration ``0002`` is exercised here too. SQLite/filesystem only: the Tier 1
legs are the adapter parity suites' job, not the runner's.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine  # noqa: E402

from backend.config import Settings  # noqa: E402
from backend.db import Repository  # noqa: E402
from backend.db.engine import build_engine, build_sessionmaker  # noqa: E402
from backend.db.models import Job, Upload  # noqa: E402
from backend.storage import ObjectStore, create_object_store  # noqa: E402
from xtalate.capabilities import Registry  # noqa: E402
from xtalate.registry import default_registry  # noqa: E402

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

# A complete POSCAR (has a lattice): converts to XYZ with loss but no recovery → a clean completion.
POSCAR_SAMPLE = b"""NaCl primitive test
1.0
  5.640  0.000  0.000
  0.000  5.640  0.000
  0.000  0.000  5.640
Na Cl
1 1
Direct
  0.00 0.00 0.00
  0.50 0.50 0.50
"""

# A molecular XYZ (no cell): XYZ → POSCAR needs a lattice, so it refuses without a recovery preset
# and completes with ``missing_lattice`` supplied — the two paths the runner tests both exercise.
XYZ_SAMPLE = b"""3
water
O  0.000  0.000  0.000
H  0.757  0.586  0.000
H -0.757  0.586  0.000
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        docs_base_url="https://docs.test/api",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'jobs.db'}",
        object_store_root=str(tmp_path / "objects"),
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    config = Config(str(_ALEMBIC_INI))
    config.cmd_opts = type("_Opts", (), {"x": [f"db_url={settings.database_url}"]})()
    command.upgrade(config, "head")
    eng = build_engine(settings)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def repository(engine: Engine) -> Repository:
    return Repository(build_sessionmaker(engine))


@pytest.fixture
def object_store(settings: Settings) -> ObjectStore:
    return create_object_store(settings)


@pytest.fixture(scope="session")
def registry() -> Registry:
    return default_registry()


@pytest.fixture
def make_upload(repository: Repository, object_store: ObjectStore) -> Callable[..., str]:
    """Store bytes + insert an Upload row, returning its ``file_id`` (the M22 stub upload)."""

    def _make(content: bytes, filename: str, *, format_override: str | None = None) -> str:
        file_id = uuid.uuid4().hex
        key = f"uploads/{file_id}"
        stored = object_store.put(key, [content])
        repository.add_upload(
            Upload(
                file_id=file_id,
                filename=filename,
                sha256=stored.sha256,
                size_bytes=stored.size,
                storage_key=key,
                format_override=format_override,
            )
        )
        return file_id

    return _make


@pytest.fixture
def submit_job(repository: Repository) -> Callable[..., str]:
    """Insert a fresh ``queued`` job and return its id (what a submit does before enqueue)."""

    def _submit(kind: str, request: dict[str, object]) -> str:
        job_id = uuid.uuid4().hex
        repository.add_job(Job(job_id=job_id, kind=kind, state="queued", request=request))
        return job_id

    return _submit
