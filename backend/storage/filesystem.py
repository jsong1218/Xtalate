"""Filesystem object store — the Tier 0 backend (no services required; Part 9 §1.1).

Keys map to files under a root directory; slash-delimited key segments become nested
subdirectories. Writes are atomic (write to a temp file in the same directory, then ``os.replace``)
so a crash mid-write never leaves a half-written object readable under its final key. This is the
backend a contributor uses when a parser bug fix needs the whole service running without Docker.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.storage.objects import (
    CHUNK_SIZE,
    ObjectNotFound,
    StoredObject,
    validate_key,
)


class FilesystemObjectStore:
    """An :class:`~backend.storage.objects.ObjectStore` backed by a local directory tree."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        return self._root / key

    def put(self, key: str, chunks: Iterable[bytes]) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        # NamedTemporaryFile in the destination directory keeps the atomic os.replace on one
        # filesystem (a cross-device rename would fail). delete=False: we rename it into place.
        tmp = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
        try:
            with tmp:
                for chunk in chunks:
                    tmp.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            os.replace(tmp.name, path)
        except BaseException:
            # Clean up the orphaned temp file on any failure (including cancellation).
            Path(tmp.name).unlink(missing_ok=True)
            raise
        return StoredObject(key=key, size=size, sha256=digest.hexdigest())

    @contextmanager
    def open(self, key: str) -> Iterator[Iterator[bytes]]:
        path = self._path(key)
        try:
            handle = path.open("rb")
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

        def _iter() -> Iterator[bytes]:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk

        try:
            yield _iter()
        finally:
            handle.close()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        path = self._path(key)
        try:
            return path.stat().st_size
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    def delete(self, key: str) -> None:
        # missing_ok makes deletion idempotent — an absent key is a no-op, per the interface.
        self._path(key).unlink(missing_ok=True)
