"""Projection + byte-availability helpers for a stored conversion (Part 6 §4.4; M24 slice 3).

The download stream (:mod:`backend.routers.downloads`) and the record/history views
(:mod:`backend.routers.conversions`) ask the same two questions about a persisted conversion — are
its output bytes still fetchable, and what filename do we offer them under — so the answers live
here, once, and cannot drift between the ``410`` gate and the ``download.available`` flag a client
polls. Nothing here reads file bytes to answer "is it gone": the check is over the record's own
columns (the lazy, storage-agnostic horizon), so it is cheap enough to run per history item. The
one case it *cannot* see — a live-but-absent object under a Tier 1 bucket rule — is caught only by
the download path, at ``open`` (:class:`~backend.storage.objects.ObjectNotFound`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.db import as_utc, utcnow
from backend.models import DownloadInfo

if TYPE_CHECKING:
    from backend.db.models import Conversion
    from backend.db.repository import Repository
    from backend.storage import ObjectStore


def default_output_name(format_id: str) -> str:
    """A format-conventional output filename (matches the CLI's ``_emit`` conventions, Part 4).

    The one place the download name is defaulted when a conversion carried no ``output_filename`` —
    read by both the record projection here and the job result (:mod:`backend.jobs.result`), so the
    name a client is told to expect and the name the download stream offers are one function. It
    lives here (the record-projection module) rather than in the worker, because both consumers are
    about *presenting* a stored conversion, not about running one.
    """
    if format_id in ("poscar", "contcar"):
        return "POSCAR" if format_id == "poscar" else "CONTCAR"
    return f"output.{format_id}"


def output_bytes_expired(conversion: Conversion) -> bool:
    """Whether a conversion's downloadable output bytes are gone (``410`` / ``available=false``).

    True when the record marks the output unavailable or keyless, or its ``output_expires_at``
    horizon has passed — the lazy, storage-agnostic check that holds on both tiers (Tier 0 has no
    bucket lifecycle at all; Tier 1's record clock agrees with the bucket rule even before the flag
    is ever touched). A live object that is nonetheless absent is caught separately at ``open``.
    """
    if not conversion.output_available or conversion.output_storage_key is None:
        return True
    expires_at = as_utc(conversion.output_expires_at)
    return expires_at is not None and expires_at < utcnow()


def download_filename(conversion: Conversion, repository: Repository) -> str:
    """The filename to offer for a conversion's output — the request's ``output_filename`` if any,
    else the format default.

    Matches the ``download.filename`` the job result advertised (:mod:`backend.jobs.result`), so the
    downloaded file carries the name the client was told to expect. The custom name lives on the
    originating job's request options, not the conversion record, so the job is read to recover it.
    """
    job = repository.get_job(conversion.job_id)
    request = job.request if job is not None and isinstance(job.request, dict) else {}
    options = request.get("options") or {}
    custom = options.get("output_filename") if isinstance(options, dict) else None
    return custom or default_output_name(conversion.target_format)


def build_download_info(
    conversion: Conversion, repository: Repository, object_store: ObjectStore
) -> DownloadInfo:
    """Project a conversion's byte-availability onto the wire :class:`DownloadInfo` (Part 6 §4.4).

    ``size_bytes`` and ``expires_at`` are populated only while the bytes are still available; once
    the output has expired they are ``None`` (a stale link renders as "expired", never a size a
    client would try to fetch). A ``size`` call that fails on an already-vanished object leaves the
    size unknown rather than raising — the availability flag, not the size, is the client's gate.
    """
    available = not output_bytes_expired(conversion)
    size_bytes: int | None = None
    expires_at: str | None = None
    if available and conversion.output_storage_key is not None:
        try:
            size_bytes = object_store.size(conversion.output_storage_key)
        except Exception:  # noqa: BLE001 - a vanished object just leaves size unknown, not a 500.
            size_bytes = None
        if conversion.output_expires_at is not None:
            expires_at = conversion.output_expires_at.isoformat()
    return DownloadInfo(
        available=available,
        # True iff validation failed — the 05 §2 download-acknowledgment gate the stream enforces.
        requires_ack=conversion.validation_status == "failed",
        filename=download_filename(conversion, repository),
        size_bytes=size_bytes,
        expires_at=expires_at,
    )
