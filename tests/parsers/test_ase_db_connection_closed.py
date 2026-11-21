"""The ASE ``.db`` reader and writer close their SQLite connection (v2.1 M77).

``ase.db`` opens a fresh ``sqlite3`` connection per operation and uses it as a context manager,
which commits but never closes. The temp file was then deleted under an open handle: harmless on
macOS and Linux, a sharing-violation error on Windows (the desktop target). Holding the database
open with ``with db:`` makes every operation share one connection, closed on exit before the temp
file goes."""

from __future__ import annotations

import gc
import io
import warnings
from pathlib import Path

from xtalate.registry import default_registry

SAMPLE = Path(__file__).parent.parent / "golden" / "ase_db" / "single-row-labeled" / "sample.db"
_REGISTRY = default_registry()


def _resource_warnings(action: object) -> list[str]:
    # Collect first, so connections other tests left open (their fixtures call ``ase.db.connect``
    # directly) are not counted against the code under test.
    gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        action()  # type: ignore[operator]
        gc.collect()
    return [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]


def test_reading_a_db_twice_leaves_no_connection_open() -> None:
    parser = _REGISTRY.get_parser("ase_db")
    data = SAMPLE.read_bytes()

    def read_twice() -> None:
        for _ in range(2):
            parser.parse(io.BytesIO(data), filename="sample.db")

    assert _resource_warnings(read_twice) == []


def test_writing_a_db_leaves_no_connection_open() -> None:
    parser = _REGISTRY.get_parser("ase_db")
    canonical = parser.parse(io.BytesIO(SAMPLE.read_bytes()), filename="s.db").canonical
    exporter = _REGISTRY.get_exporter("ase_db")

    def write() -> None:
        exporter.export(canonical, io.BytesIO())

    assert _resource_warnings(write) == []
