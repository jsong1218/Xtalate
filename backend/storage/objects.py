"""The object-storage interface, plus the key rules and the backend factory (v0.5 M21 slice 2).

Object storage holds the *bytes* the service moves: uploaded inputs and converted outputs. The
interface is deliberately small — put, open, exists, size, delete — because that is all the upload
(M24) and download (M24) surfaces need, and a small interface is what keeps two backends honestly
interchangeable. Expiry is **not** here: bytes expire via the storage platform's own lifecycle
rules (bucket lifecycle for S3, an init-job policy locally), never an application cron (Part 9
§5.2) — the adapter neither schedules nor performs deletion-on-a-timer.

Two backends satisfy this interface: :class:`~backend.storage.filesystem.FilesystemObjectStore`
(Tier 0, no services) and :class:`~backend.storage.s3.S3ObjectStore` (Tier 1, MinIO/S3). They are
selected by configuration through :func:`create_object_store`; the rest of the service depends only
on the interface.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from backend.config import Settings

#: Streaming read/write chunk size (256 KiB) — large enough to amortize per-chunk overhead, small
#: enough that no whole file is ever held in memory (the M24 "never whole-file in API memory" rule).
CHUNK_SIZE = 256 * 1024

# A storage key is a forward-slash-delimited path of safe segments. Server-generated only (a
# ``file_id``/``conversion_id`` under a prefix), never user-supplied — so this validation guards
# against a programming error (an accidental ``..`` or absolute path reaching the filesystem
# backend), not against hostile input. Segments are word-ish; no empty, ``.`` or ``..`` segments,
# no leading/trailing slash.
_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ObjectNotFound(KeyError):
    """Raised by :meth:`ObjectStore.open` / :meth:`ObjectStore.size` when a key does not exist.

    A subclass of ``KeyError`` so callers may catch either; the transport layer (M24) maps it to a
    ``410 OUTPUT_EXPIRED`` / ``404`` envelope, never letting it surface as a 500.
    """


@dataclass(frozen=True, slots=True)
class StoredObject:
    """The result of a :meth:`ObjectStore.put`: the key, the byte count, and the content hash.

    The ``sha256`` is computed in the same single streaming pass that stores the bytes — both
    backends produce it identically, which is what lets the upload surface (M24) return the digest
    in ``UploadResponse`` without a second read, and what the parity suite asserts is equal.
    """

    key: str
    size: int
    sha256: str


@runtime_checkable
class ObjectStore(Protocol):
    """The one interface both object-storage backends implement (Part 9 §1.1).

    Keys are server-generated slash-delimited paths (see :func:`validate_key`). Every method is
    synchronous: the backends do blocking I/O, and the service runs them in a worker/threadpool
    rather than pretending the I/O is async. ``put`` consumes an iterable of byte chunks so no
    whole file is buffered; ``open`` yields the object the same way for streaming downloads.
    """

    def put(self, key: str, chunks: Iterable[bytes]) -> StoredObject:
        """Store the concatenated ``chunks`` under ``key`` (overwriting); returns size + sha256."""
        ...

    def open(self, key: str) -> AbstractContextManager[Iterator[bytes]]:
        """Open ``key`` for streaming reads; raises :class:`ObjectNotFound` if it is absent."""
        ...

    def exists(self, key: str) -> bool:
        """Whether ``key`` currently holds an object."""
        ...

    def size(self, key: str) -> int:
        """Byte length of ``key``; raises :class:`ObjectNotFound` if it is absent."""
        ...

    def delete(self, key: str) -> None:
        """Remove ``key``. Idempotent: deleting an absent key is a no-op, never an error."""
        ...


def validate_key(key: str) -> str:
    """Return ``key`` unchanged if it is a well-formed storage key, else raise ``ValueError``.

    Rejects empty keys, absolute paths, and any ``.``/``..`` or malformed segment — the guard that
    keeps a filesystem-backed store from escaping its root. Keys are server-minted, so a rejection
    here is a bug in the caller, not a client error.
    """
    if not key or key.startswith("/") or key.endswith("/"):
        raise ValueError(f"invalid storage key: {key!r}")
    segments = key.split("/")
    if not all(_KEY_SEGMENT.match(segment) for segment in segments):
        raise ValueError(f"invalid storage key: {key!r}")
    return key


def create_object_store(settings: Settings) -> ObjectStore:
    """Build the configured object-storage backend (``filesystem`` or ``s3``).

    The composition root for object storage: the rest of the service receives an
    :class:`ObjectStore` and never learns which backend it is. An unknown backend name fails loudly
    at startup rather than at first request.
    """
    backend = settings.object_store_backend.lower()
    if backend == "filesystem":
        from pathlib import Path

        from backend.storage.filesystem import FilesystemObjectStore

        return FilesystemObjectStore(Path(settings.object_store_root))
    if backend == "s3":
        from backend.storage.s3 import S3ObjectStore

        return S3ObjectStore(
            bucket=settings.object_store_bucket,
            endpoint_url=settings.object_store_endpoint,
            region=settings.object_store_region,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
        )
    raise ValueError(
        f"unknown object_store_backend {settings.object_store_backend!r} "
        "(expected 'filesystem' or 's3')"
    )
