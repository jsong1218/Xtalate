"""Shared fixtures for the backend (service) test suite.

The service dependencies (FastAPI, pydantic-settings, httpx) ship in the ``dev`` extra, so these
tests run in the ordinary CI gate. The ``importorskip`` guard keeps the suite from erroring in the
edge case of a library-only environment that installed ``xtalate`` without the dev extra — matching
the toyfmt fixture's "skip when the dependency is absent" pattern.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")
pytest.importorskip("httpx", reason="httpx (TestClient transport) not installed")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.db import Repository  # noqa: E402

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _migrate(database_url: str) -> None:
    """Run the Alembic chain to ``head`` against ``database_url`` (the M22 job/upload tables)."""
    config = Config(str(_ALEMBIC_INI))
    config.cmd_opts = type("_Opts", (), {"x": [f"db_url={database_url}"]})()  # get_x_argument
    command.upgrade(config, "head")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A deterministic settings object — never reads the ambient environment or a stray ``.env``.

    The persistence adapters point at per-test temp paths (an isolated SQLite file and object-store
    root), so building the app touches no repo-root default and each test starts from a clean slate.
    """
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        docs_base_url="https://docs.test/api",
        max_upload_bytes=1234,
        report_retention_days=7,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'service.db'}",
        object_store_root=str(tmp_path / "objects"),
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A ``TestClient`` over an app built from the deterministic ``settings`` (isolated).

    Entered as a context manager so the app's lifespan runs — startup and, on teardown, the
    shutdown that disposes the engine's pool (no SQLite connections leaked between tests).
    """
    # Migrate the isolated temp database before the app opens it, so the M22 job/upload endpoints
    # have their tables (the stateless M21 endpoints did not need any).
    _migrate(settings.database_url)
    # raise_server_exceptions=False so the 500-path test exercises the real envelope handler
    # instead of re-raising into the test process.
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def build_client(settings: Settings) -> Iterator[Callable[..., TestClient]]:
    """A factory for a ``TestClient`` over an app built from ``settings`` with field overrides.

    The M24 limits/auth surfaces need per-test configuration (a low rate limit, a small job cap,
    a configured API key) without mutating the shared ``settings`` object. Each built client shares
    the same isolated temp database (migrated once), so seeded rows are visible across them; every
    client is entered as a context manager and torn down at the end of the test.
    """
    _migrate(settings.database_url)
    built: list[TestClient] = []

    def _build(**overrides: Any) -> TestClient:
        cfg = settings.model_copy(update=overrides) if overrides else settings
        client = TestClient(create_app(cfg), raise_server_exceptions=False)
        client.__enter__()
        built.append(client)
        return client

    yield _build
    for client in built:
        client.__exit__(None, None, None)


@pytest.fixture
def repository(client: TestClient) -> Repository:
    """The running app's :class:`~backend.db.Repository`, typed.

    ``TestClient.app`` is an untyped ASGI callable, so a test that reaches ``client.app.state``
    for the app's own adapters gets no type from it. Confining that one unavoidable reach to this
    fixture keeps the state-inspecting tests (expiry sweeps, post-cancel row assertions) type-clean
    instead of scattering ``# type: ignore`` through the suite.
    """
    return cast(Repository, client.app.state.repository)  # type: ignore[attr-defined]
