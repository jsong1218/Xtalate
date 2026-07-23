"""``GET /v1/download/{conversion_id}`` — stream a converted output's bytes (M24 deliverable 2).

The output bytes never leave through a presigned URL: a download always streams *through the API*
from private object storage (Part 9 §5.3), chunk by chunk, so no whole file is held in API memory
(the same "never whole-file in API memory" rule the upload obeys). Three refusals guard the stream,
each a spec-stable envelope code, not a generic error:

* **``404 CONVERSION_NOT_FOUND``** — no such conversion record (or it has passed report retention).
* **``409 VALIDATION_ACK_REQUIRED``** — the conversion's automatic validation *failed*, and the
  client has not acknowledged it. A failed-validation output is downloadable only with an explicit
  ``?acknowledge_validation_failure=true`` (Part 5 §2's download-acknowledgment gate): the client
  must confirm it accepts an output the service could not verify round-trips within tolerance.
* **``410 OUTPUT_EXPIRED``** — the output bytes are gone. The record and its reports **outlive** the
  bytes (reports-outlive-bytes), so this is a clean 410, never a 404: the conversion still exists,
  only its downloadable bytes have passed their lifecycle window. Detected three ways, because the
  byte-lifecycle sweep is the storage platform's, not the app's: the record's ``output_available``
  flag is false, or its ``output_expires_at`` horizon has passed (the lazy check Tier 0 relies on,
  and the Tier 1 record clock that agrees with the bucket rule *before* the flag is ever updated),
  or the object is simply absent (:class:`ObjectNotFound` — the Tier 1 bucket-lifecycle case, where
  the bytes vanish with no DB write at all).

The endpoint holds no scientific logic: it reads the conversion record, resolves the bytes, and
streams them under a ``Content-Disposition`` naming the same file the job result advertised.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from backend.db import Repository, as_utc, utcnow
from backend.deps import get_object_store, get_repository
from backend.errors import ApiError
from backend.jobs.runner import _default_output_name
from backend.storage import ObjectStore
from backend.storage.objects import ObjectNotFound

if TYPE_CHECKING:
    from backend.db.models import Conversion

router = APIRouter()


@router.get("/download/{conversion_id}", tags=["conversions"])
def download(
    conversion_id: str,
    acknowledge_validation_failure: bool = Query(
        default=False,
        description=(
            "Acknowledge a failed automatic validation to download the output anyway "
            "(required when the conversion's validation_status is 'failed')."
        ),
    ),
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
) -> StreamingResponse:
    """Stream a conversion's output bytes, guarded by the not-found / ack / expiry gates above."""
    conversion = repository.get_conversion(conversion_id)
    if conversion is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONVERSION_NOT_FOUND",
            message=f"No conversion {conversion_id!r}.",
        )

    if _output_expired(conversion):
        raise _output_expired_error(conversion_id)

    # The failed-validation gate (Part 5 §2): an output the service could not verify is downloadable
    # only when the client explicitly accepts it. Checked after expiry — acknowledging one's way to
    # bytes that no longer exist is impossible, so "it's gone" (410) is the more honest answer when
    # both hold.
    if conversion.validation_status == "failed" and not acknowledge_validation_failure:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="VALIDATION_ACK_REQUIRED",
            message=(
                "Automatic validation failed for this conversion; re-request with "
                "?acknowledge_validation_failure=true to download the unverified output."
            ),
            details={"validation_status": conversion.validation_status},
        )

    key = conversion.output_storage_key
    if key is None:  # pragma: no cover - _output_expired already covers a null key.
        raise _output_expired_error(conversion_id)

    # Enter the store's context manager eagerly so a missing object becomes a 410 *before* any
    # response has begun — never a half-sent stream that fails mid-body. The manager is closed when
    # the streaming generator is exhausted (or the client disconnects and it is GC'd).
    manager = object_store.open(key)
    try:
        chunks = manager.__enter__()
    except ObjectNotFound as exc:
        raise _output_expired_error(conversion_id) from exc

    filename = _download_filename(conversion, repository)
    return StreamingResponse(
        _drain(manager, chunks),
        media_type="application/octet-stream",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def _output_expired(conversion: Conversion) -> bool:
    """Whether a conversion's downloadable bytes are gone (the ``410`` condition).

    True when the record marks the output unavailable or keyless, or its ``output_expires_at``
    horizon has passed — the lazy, storage-agnostic check that holds on both tiers (Tier 0 has no
    bucket lifecycle at all; Tier 1's record clock agrees with the bucket rule even before the flag
    is ever touched). A live object that is nonetheless absent is caught separately at ``open``.
    """
    if not conversion.output_available or conversion.output_storage_key is None:
        return True
    expires_at = as_utc(conversion.output_expires_at)
    return expires_at is not None and expires_at < utcnow()


def _output_expired_error(conversion_id: str) -> ApiError:
    return ApiError(
        status_code=status.HTTP_410_GONE,
        code="OUTPUT_EXPIRED",
        message=(
            f"The converted output for {conversion_id!r} is no longer available; "
            "its reports remain retrievable via GET /v1/conversions/{id}."
        ),
    )


def _drain(
    manager: AbstractContextManager[Iterator[bytes]], chunks: Iterator[bytes]
) -> Iterator[bytes]:
    """Yield the object's chunks, then close the (already-entered) store context manager."""
    try:
        yield from chunks
    finally:
        manager.__exit__(None, None, None)


def _download_filename(conversion: Conversion, repository: Repository) -> str:
    """The filename to offer — the request's ``output_filename`` if any, else the format default.

    Matches the ``download.filename`` the job result advertised (``backend.jobs.result``), so the
    downloaded file carries the name the client was told to expect. The custom name lives on the
    originating job's request options, not the conversion record, so the job is read to recover it.
    """
    job = repository.get_job(conversion.job_id)
    request = job.request if job is not None and isinstance(job.request, dict) else {}
    options = request.get("options") or {}
    custom = options.get("output_filename") if isinstance(options, dict) else None
    return custom or _default_output_name(conversion.target_format)


def _content_disposition(filename: str) -> str:
    """A header-injection-safe ``attachment`` disposition for ``filename`` (RFC 6266).

    ``output_filename`` is client-supplied and unvalidated, so a name could carry quotes, newlines,
    or non-ASCII. The plain ``filename=`` token is stripped to a quote/control-free ASCII fallback;
    the RFC 5987 ``filename*=`` carries the exact UTF-8 name percent-encoded for a modern client.
    """
    ascii_fallback = re.sub(r"[^\x20-\x7e]", "_", filename)
    ascii_fallback = re.sub(r'["\\]', "_", ascii_fallback).strip() or "download"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
