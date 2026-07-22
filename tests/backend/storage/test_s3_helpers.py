"""Unit tests for the S3 backend's internals that need no server (M21 slice 2).

The full S3 behaviour is covered by the parity suite when a MinIO endpoint is configured; these
tests pin the pure logic — the streaming hash reader and the not-found classifier — so a regression
in either is caught in the ordinary gate, without Docker.
"""

from __future__ import annotations

import hashlib

from backend.storage.s3 import _HashingChunkReader, _is_not_found


def test_hashing_reader_read_all_matches_hashlib() -> None:
    parts = [b"alpha", b"beta", b"gamma" * 100]
    expected = b"".join(parts)
    reader = _HashingChunkReader(iter(parts))
    assert reader.read(-1) == expected
    assert reader.size == len(expected)
    assert reader.sha256 == hashlib.sha256(expected).hexdigest()


def test_hashing_reader_partial_reads_reassemble() -> None:
    parts = [b"0123456789", b"abcdefghij"]
    expected = b"".join(parts)
    reader = _HashingChunkReader(iter(parts))
    out = bytearray()
    while True:
        block = reader.read(7)  # amt that does not align to chunk boundaries
        if not block:
            break
        out.extend(block)
    assert bytes(out) == expected
    assert reader.size == len(expected)
    assert reader.sha256 == hashlib.sha256(expected).hexdigest()


def test_hashing_reader_empty() -> None:
    reader = _HashingChunkReader(iter([]))
    assert reader.read(1024) == b""
    assert reader.size == 0
    assert reader.sha256 == hashlib.sha256(b"").hexdigest()


class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def test_is_not_found_classifies_missing_codes() -> None:
    assert _is_not_found(_FakeClientError("404")) is True
    assert _is_not_found(_FakeClientError("NoSuchKey")) is True
    assert _is_not_found(_FakeClientError("NotFound")) is True


def test_is_not_found_rejects_real_errors() -> None:
    assert _is_not_found(_FakeClientError("AccessDenied")) is False
    assert _is_not_found(_FakeClientError("InternalError")) is False
