"""Shared fixtures for the backend (service) test suite.

The service dependencies (FastAPI, pydantic-settings, httpx) ship in the ``dev`` extra, so these
tests run in the ordinary CI gate. The ``importorskip`` guard keeps the suite from erroring in the
edge case of a library-only environment that installed ``xtalate`` without the dev extra — matching
the toyfmt fixture's "skip when the dependency is absent" pattern.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="service extra not installed")
pytest.importorskip("httpx", reason="httpx (TestClient transport) not installed")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.config import Settings  # noqa: E402


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
    # raise_server_exceptions=False so the 500-path test exercises the real envelope handler
    # instead of re-raising into the test process.
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client
