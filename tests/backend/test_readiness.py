"""The readiness probes report reachability, and never raise (v0.5 M21 slice 4).

Each probe is exercised twice — a reachable dependency (green) and an unreachable one (a
``ReadinessCheck(ok=False, ...)``, *not* an exception), the contract the health endpoint relies on
to report on a dead dependency rather than crash with it. The probes are async; a sync test drives
them through ``asyncio.run`` so no extra plugin is needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine

from backend.models import ReadinessCheck
from backend.readiness import ReadinessProbe, database_probe, object_store_probe
from backend.storage.filesystem import FilesystemObjectStore
from backend.storage.objects import StoredObject


def _run(probe: ReadinessProbe) -> ReadinessCheck:
    """Drive an async probe to its result — a coroutine wrapper so ``asyncio.run`` types cleanly."""

    async def _call() -> ReadinessCheck:
        return await probe()

    return asyncio.run(_call())


def test_database_probe_green_on_reachable_engine(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'probe.db'}")
    try:
        check = _run(database_probe(engine))
    finally:
        engine.dispose()
    assert check.ok is True
    assert check.detail == "sqlite"


def test_database_probe_red_on_unreachable_engine() -> None:
    # A path under a directory that cannot be created — SQLite fails to open, the probe reports it.
    engine = create_engine("sqlite+pysqlite:////nonexistent-xtalate-dir/does/not/exist.db")
    try:
        check = _run(database_probe(engine))
    finally:
        engine.dispose()
    assert check.ok is False
    assert check.detail is not None
    assert check.detail.startswith("sqlite: ")  # "<kind>: <ExceptionType>", never a path or secret


def test_object_store_probe_green_on_reachable_store(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path / "objects")
    check = _run(object_store_probe(store, "filesystem"))
    assert check.ok is True
    assert check.detail == "filesystem"


class _BrokenStore:
    """An :class:`~backend.storage.objects.ObjectStore` whose reads always fail (a down backend)."""

    def put(self, key: str, chunks: Iterable[bytes]) -> StoredObject:  # pragma: no cover - unused
        raise ConnectionError("backend down")

    @contextmanager
    def open(self, key: str) -> Iterator[Iterator[bytes]]:  # pragma: no cover - unused
        raise ConnectionError("backend down")
        yield iter(())

    def exists(self, key: str) -> bool:
        raise ConnectionError("backend down")

    def size(self, key: str) -> int:  # pragma: no cover - unused
        raise ConnectionError("backend down")

    def delete(self, key: str) -> None:  # pragma: no cover - unused
        raise ConnectionError("backend down")


def test_object_store_probe_red_on_unreachable_store() -> None:
    check = _run(object_store_probe(_BrokenStore(), "s3"))
    assert check.ok is False
    assert check.detail == "s3: ConnectionError"
