"""Filesystem-backend specifics, the factory, and key validation (no services; M21 slice 2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from backend.config import Settings
from backend.storage import create_object_store
from backend.storage.filesystem import FilesystemObjectStore
from backend.storage.objects import validate_key


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg,arg-type]


def test_factory_builds_filesystem_backend(tmp_path: Path) -> None:
    store = create_object_store(
        _settings(object_store_backend="filesystem", object_store_root=str(tmp_path))
    )
    assert isinstance(store, FilesystemObjectStore)


def test_factory_builds_s3_backend_without_connecting() -> None:
    # boto3.client() constructs a client lazily and does not open a connection, so this succeeds
    # offline — proving the s3 branch wires up, without needing MinIO.
    from backend.storage.s3 import S3ObjectStore

    store = create_object_store(
        _settings(object_store_backend="s3", object_store_endpoint="http://localhost:9000")
    )
    assert isinstance(store, S3ObjectStore)


def test_factory_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="unknown object_store_backend"):
        create_object_store(_settings(object_store_backend="carrier-pigeon"))


def test_filesystem_root_is_created(tmp_path: Path) -> None:
    root = tmp_path / "does" / "not" / "exist" / "yet"
    FilesystemObjectStore(root)
    assert root.is_dir()


def test_filesystem_write_is_atomic_no_temp_left(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    store.put("a/b.bin", [b"data"])
    # Only the final object should remain — no leftover NamedTemporaryFile in the directory.
    assert [p.name for p in (tmp_path / "a").iterdir()] == ["b.bin"]


def test_filesystem_put_cleans_up_temp_on_failure(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)

    def exploding() -> Iterator[bytes]:
        yield b"partial"
        raise RuntimeError("boom mid-stream")

    with pytest.raises(RuntimeError, match="boom"):
        store.put("x.bin", exploding())
    # No object and no orphaned temp file survive the failed write.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "bad",
    ["", "/leading", "trailing/", "a//b", "../escape", "a/../b", "a/./b", "a/b\\c", "a b"],
)
def test_validate_key_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid storage key"):
        validate_key(bad)


@pytest.mark.parametrize("good", ["a", "a/b/c", "file.bin", "u_1/2026-07/OUT.poscar", "a.b.c"])
def test_validate_key_accepts_safe(good: str) -> None:
    assert validate_key(good) == good


def test_filesystem_rejects_traversal_key_at_use(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    with pytest.raises(ValueError, match="invalid storage key"):
        store.put("../escape.bin", [b"nope"])
