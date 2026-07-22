"""One suite, both backends — the object-store interface behaves identically (M21 slice 2).

Every test here takes the parametrized ``object_store`` fixture, so it runs against the filesystem
backend (always) and the S3 backend (when configured). If the two ever diverge, the divergent
backend's parametrization fails — parity is verified, not assumed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator

import pytest

from backend.storage.objects import CHUNK_SIZE, ObjectNotFound, ObjectStore


def _read_all(store: ObjectStore, key: str) -> bytes:
    with store.open(key) as stream:
        return b"".join(stream)


def test_put_reports_size_and_sha256(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("hello.bin")
    payload = b"hello world" * 100
    stored = object_store.put(key, [payload])
    assert stored.key == key
    assert stored.size == len(payload)
    assert stored.sha256 == hashlib.sha256(payload).hexdigest()


def test_roundtrip_exact_bytes(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("round.bin")
    payload = b"the exact bytes, preserved"
    object_store.put(key, [payload])
    assert _read_all(object_store, key) == payload


def test_binary_safe(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("binary.bin")
    payload = bytes(range(256)) * 4  # nulls, high bytes, everything
    object_store.put(key, [payload])
    assert _read_all(object_store, key) == payload


def test_large_multichunk_payload(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    # Exceed one CHUNK_SIZE so both the write and the read path cross chunk boundaries.
    key = keys("large.bin")
    payload = b"x" * (CHUNK_SIZE * 2 + 777)
    stored = object_store.put(key, [payload])
    assert stored.size == len(payload)
    assert _read_all(object_store, key) == payload


def test_put_from_a_streamed_iterator(
    object_store: ObjectStore, keys: Callable[[str], str]
) -> None:
    key = keys("streamed.bin")
    parts = [b"chunk-a" * 1000, b"chunk-b" * 1000, b"chunk-c" * 1000]
    expected = b"".join(parts)

    def gen() -> Iterator[bytes]:
        yield from parts

    stored = object_store.put(key, gen())
    assert stored.sha256 == hashlib.sha256(expected).hexdigest()
    assert _read_all(object_store, key) == expected


def test_exists_and_size(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("present.bin")
    assert object_store.exists(key) is False
    object_store.put(key, [b"12345"])
    assert object_store.exists(key) is True
    assert object_store.size(key) == 5


def test_overwrite_replaces_content(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("over.bin")
    object_store.put(key, [b"first-and-longer"])
    object_store.put(key, [b"second"])
    assert _read_all(object_store, key) == b"second"
    assert object_store.size(key) == len(b"second")


def test_delete_then_absent(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("gone.bin")
    object_store.put(key, [b"bye"])
    object_store.delete(key)
    assert object_store.exists(key) is False


def test_delete_is_idempotent(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("never.bin")
    # Deleting a key that never existed is a no-op, not an error (interface contract).
    object_store.delete(key)
    object_store.delete(key)


def test_open_missing_raises_not_found(
    object_store: ObjectStore, keys: Callable[[str], str]
) -> None:
    with pytest.raises(ObjectNotFound):
        with object_store.open(keys("absent.bin")) as stream:
            b"".join(stream)


def test_size_missing_raises_not_found(
    object_store: ObjectStore, keys: Callable[[str], str]
) -> None:
    with pytest.raises(ObjectNotFound):
        object_store.size(keys("absent.bin"))


def test_nested_key(object_store: ObjectStore, keys: Callable[[str], str]) -> None:
    key = keys("uploads/2026/deep.bin")
    object_store.put(key, [b"nested"])
    assert _read_all(object_store, key) == b"nested"
