"""``POST /v1/upload`` — the M22 **stub** direct-to-storage path (Part 6 §2; hardened in M24).

The job pipeline needs a ``file_id`` to convert, so M22 ships a minimal upload: read the multipart
file, stream it into object storage, record the :class:`~backend.db.models.Upload` row, and return
its handle. What it deliberately does **not** yet do is the M24 work — bounded streaming with a
``413 FILE_TOO_LARGE`` at ``max_upload_bytes``, per-caller rate limiting, and the frame pre-check.
The endpoint's *contract* (the :class:`~backend.models.UploadResponse`) is the final one, so M24
replaces the body beneath a stable surface (**P6**); this docstring is the marker that it is a stub.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from backend.config import Settings
from backend.db import Repository, utcnow
from backend.db.models import Upload
from backend.deps import get_object_store, get_repository, get_settings
from backend.models import UploadResponse
from backend.storage import ObjectStore
from backend.storage.objects import CHUNK_SIZE

router = APIRouter()


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    file_id = uuid.uuid4().hex
    storage_key = f"uploads/{file_id}"

    # Read the multipart part in bounded chunks and hand them to the store, which computes the
    # sha256 in the same pass (StoredObject) — so no whole file is held beyond a chunk, and the
    # digest needs no second read. (M24 adds the running size cap that turns this into a 413.)
    def _chunks() -> object:
        while True:
            chunk = file.file.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    stored = object_store.put(storage_key, _chunks())  # type: ignore[arg-type]
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
