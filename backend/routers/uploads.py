"""``POST /v1/upload`` — bounded streaming to object storage (Part 6 §2.2, §5; M24 deliverable 1).

The job pipeline needs a ``file_id`` to convert. The handler reads Starlette's spooled multipart
part in bounded chunks and hands them to object storage, which computes the sha256 in the same pass.
Two boundaries, stated precisely so the guarantee is not overclaimed:

* **Never whole-file in API *memory*.** Starlette spools the multipart body to a
  ``SpooledTemporaryFile`` (in memory only up to a small threshold, then on disk), and this handler
  streams from that spool to object storage a chunk at a time — so the API process never holds the
  whole payload resident (Part 9 §5.3), and the digest needs no second read.
* **The size gate rejects during that copy, not during the network receive.** A running byte total
  is compared against ``max_upload_bytes`` as each chunk is pulled, so an over-limit upload is a
  ``413 FILE_TOO_LARGE`` with its partial object deleted and **no ``Upload`` row written** — the
  oversized bytes never reach object storage and are never buffered whole in memory. The multipart
  body has already been received (and spooled) by the framework before the handler runs, so this is
  not a mid-network-stream abort; the guarantee is about storage and memory, not about refusing the
  transfer itself. (A future front-proxy ``client_max_body_size`` is the mid-transfer cut, Part 9.)

The handler is a plain ``def`` (not ``async``): every call it makes — the spool read and the
object-store ``put`` — is blocking I/O, so FastAPI runs it in a threadpool and the event loop is
never blocked (an ``async def`` here would stall every concurrent request during a large upload).

The endpoint's *contract* (the :class:`~backend.models.UploadResponse`) is the M22 one, unchanged:
M24 replaced the body beneath a stable surface (**P6**).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from backend.config import Settings
from backend.db import Repository, utcnow
from backend.db.models import Upload
from backend.deps import get_object_store, get_repository, get_settings
from backend.errors import ApiError
from backend.models import UploadResponse
from backend.storage import ObjectStore
from backend.storage.objects import CHUNK_SIZE

router = APIRouter()


class _UploadTooLarge(Exception):
    """Raised by the bounded chunk generator when the running total exceeds ``max_upload_bytes``.

    A private sentinel, not an :class:`ApiError`: it fires *inside* the object store's ``put`` (as
    it pulls the next chunk), so it must travel back out through ``put`` before the endpoint can
    delete the partial object and render the ``413`` envelope. Turning it into the ``ApiError`` at
    the ``put`` boundary keeps the store ignorant of transport concerns.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"upload exceeds {limit} bytes")


def _bounded_chunks(file: UploadFile, limit: int) -> Iterator[bytes]:
    """Yield the upload's bytes in ``CHUNK_SIZE`` pieces, aborting once ``limit`` is exceeded.

    The total is checked *before* each over-limit chunk is yielded, so the store never writes a
    byte past the cap. A file exactly at the limit is accepted; the first byte beyond it aborts.
    """
    total = 0
    while True:
        chunk = file.file.read(CHUNK_SIZE)
        if not chunk:
            return
        total += len(chunk)
        if total > limit:
            raise _UploadTooLarge(limit)
        yield chunk


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload(
    file: UploadFile = File(...),
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    file_id = uuid.uuid4().hex
    storage_key = f"uploads/{file_id}"

    try:
        stored = object_store.put(storage_key, _bounded_chunks(file, settings.max_upload_bytes))
    except _UploadTooLarge as exc:
        # Clean up whatever the store wrote before the abort (idempotent; a no-op if nothing
        # landed), then refuse. No Upload row is created — an over-limit upload leaves no trace.
        object_store.delete(storage_key)
        raise ApiError(
            status_code=413,  # literal, not status.HTTP_413_* (the constant is deprecated upstream)
            code="FILE_TOO_LARGE",
            message=f"Upload exceeds the {exc.limit}-byte limit.",
            details={"max_upload_bytes": exc.limit},
        ) from exc

    expires_at = utcnow() + timedelta(hours=settings.upload_retention_hours)
    repository.add_upload(
        Upload(
            file_id=file_id,
            filename=file.filename,
            sha256=stored.sha256,
            size_bytes=stored.size,
            content_type=file.content_type,
            storage_key=storage_key,
            expires_at=expires_at,
        )
    )
    return UploadResponse(
        file_id=file_id,
        filename=file.filename or "",
        size_bytes=stored.size,
        sha256=stored.sha256,
        expires_at=expires_at.isoformat(),
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    file_id: str,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
) -> Response:
    """Immediately remove an uploaded file — its bytes and its row (Part 6 §5, M24 deliverable 3).

    The user-initiated counterpart to the storage lifecycle's timed byte sweep: a client that
    uploaded a file it did not mean to keep can delete it now rather than waiting out the retention
    window. The object bytes go first (idempotent — a no-op if the lifecycle rule already swept
    them), then the row; ``ON DELETE SET NULL`` nulls any conversion's ``source_file_id``, so
    conversions produced from this file and their reports **survive** (reports-outlive-bytes). A
    successful delete is ``204`` with no body; an unknown file is ``404 FILE_NOT_FOUND``.
    """
    upload = repository.get_upload(file_id)
    if upload is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="FILE_NOT_FOUND",
            message=f"No uploaded file {file_id!r}.",
        )
    object_store.delete(upload.storage_key)
    repository.delete_upload(file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
