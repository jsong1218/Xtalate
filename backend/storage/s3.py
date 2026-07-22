"""S3-compatible object store — the Tier 1 backend (MinIO locally, any S3 in production).

Uses **boto3** (DECISIONS.md D80) against a configurable endpoint, so the same code serves MinIO in
the Tier 1 compose stack and a cloud S3 in a hosted deployment. boto3 is untyped upstream (like
ASE, D7); it is confined to this one module and its return values are converted to concrete types
at the boundary, so the ``Any`` never leaks into the typed service.

``put`` streams the byte chunks straight through boto3's uploader while a hashing wrapper computes
the sha256 and size in the same pass — no whole file is buffered, matching the filesystem backend's
contract exactly (the parity suite asserts the two produce identical digests). Downloads stream via
``get_object`` (Part 9 §5.3: downloads stream through the API; the service never hands out a
presigned URL to a private object).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from backend.storage.objects import CHUNK_SIZE, ObjectNotFound, StoredObject, validate_key


class _HashingChunkReader:
    """A minimal read-only file object over an iterable of byte chunks.

    boto3's uploader pulls bytes with ``read(amt)``; this adapts a chunk iterable to that shape
    while accumulating the sha256 and byte count as the bytes flow through — one pass, no buffering
    of the whole payload. Reads are sequential (the uploader is configured single-threaded), so the
    digest is taken over the file's byte order.
    """

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._iter = iter(chunks)
        self._buffer = bytearray()
        self._digest = hashlib.sha256()
        self.size = 0

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def read(self, amt: int = -1) -> bytes:
        if amt is None or amt < 0:
            # Drain everything (boto3 does this for small single-part uploads).
            for chunk in self._iter:
                self._buffer.extend(chunk)
            out = bytes(self._buffer)
            self._buffer.clear()
            self._account(out)
            return out
        while len(self._buffer) < amt:
            try:
                self._buffer.extend(next(self._iter))
            except StopIteration:
                break
        out = bytes(self._buffer[:amt])
        del self._buffer[:amt]
        self._account(out)
        return out

    def _account(self, data: bytes) -> None:
        self._digest.update(data)
        self.size += len(data)


class S3ObjectStore:
    """An :class:`~backend.storage.objects.ObjectStore` backed by an S3-compatible bucket."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None,
        region: str,
        access_key: str | None,
        secret_key: str | None,
    ) -> None:
        import boto3
        from boto3.s3.transfer import TransferConfig
        from botocore.config import Config

        self._bucket = bucket
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )
        # Single-threaded transfer so the hashing reader sees bytes in file order (a concurrent
        # multipart upload would read the reader out of order and corrupt the digest).
        self._transfer = TransferConfig(use_threads=False)

    def put(self, key: str, chunks: Iterable[bytes]) -> StoredObject:
        validate_key(key)
        reader = _HashingChunkReader(chunks)
        self._client.upload_fileobj(reader, self._bucket, key, Config=self._transfer)
        return StoredObject(key=key, size=reader.size, sha256=reader.sha256)

    @contextmanager
    def open(self, key: str) -> Iterator[Iterator[bytes]]:
        validate_key(key)
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFound(key) from exc
            raise
        body = response["Body"]

        def _iter() -> Iterator[bytes]:
            yield from body.iter_chunks(CHUNK_SIZE)

        try:
            yield _iter()
        finally:
            body.close()

    def exists(self, key: str) -> bool:
        validate_key(key)
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise
        return True

    def size(self, key: str) -> int:
        validate_key(key)
        from botocore.exceptions import ClientError

        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFound(key) from exc
            raise
        return int(response["ContentLength"])

    def delete(self, key: str) -> None:
        validate_key(key)
        # S3 delete of an absent key succeeds, so this is idempotent without a pre-check.
        self._client.delete_object(Bucket=self._bucket, Key=key)


def _is_not_found(exc: Any) -> bool:
    """Whether a botocore ``ClientError`` is a 404 / missing-key (vs a real error to re-raise)."""
    error = getattr(exc, "response", {}).get("Error", {})
    code = error.get("Code", "")
    return code in {"404", "NoSuchKey", "NotFound"}
