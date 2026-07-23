"""Assemble a completed job's ``result`` payload from its persisted rows (Part 6 §3.2).

The job envelope's ``result`` is kind-specific and embeds the library's report models **verbatim**.
Rather than duplicate that assembly in the worker and again on every poll, it lives here, reading
the one source of truth — the stored reports and conversion record. So ``GET /v1/jobs/{job_id}`` on
a completed job returns byte-for-byte what the worker persisted, and the verbatim guarantee holds at
both ends. A non-completed job has no result (``None``); a failed job's ``error`` rides instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from backend.jobs.runner import _default_output_name

if TYPE_CHECKING:
    from backend.db.models import Job, Report
    from backend.db.repository import Repository
    from backend.storage import ObjectStore


def build_job_result(
    job: Job, repository: Repository, object_store: ObjectStore
) -> dict[str, Any] | None:
    """The completion payload for ``job``, or ``None`` if it has not completed."""
    if job.state != "completed":
        return None
    reports = repository.get_reports_for_job(job.job_id)
    if job.kind == "inspect":
        discovery = _first(reports, "discovery")
        return {"discovery_report": discovery.body} if discovery is not None else None
    if job.kind == "convert":
        return _convert_result(job, reports, repository, object_store)
    if job.kind == "validate":
        validation = _first(reports, "validation")
        return {"validation_report": validation.body} if validation is not None else None
    return None


def _convert_result(
    job: Job, reports: Sequence[Report], repository: Repository, object_store: ObjectStore
) -> dict[str, Any] | None:
    conversion_report = _first(reports, "conversion")
    if conversion_report is None or conversion_report.conversion_id is None:
        return None
    validation_report = _first(reports, "validation")
    conversion = repository.get_conversion(conversion_report.conversion_id)
    if conversion is None:
        return None

    options = job.request.get("options") or {} if isinstance(job.request, dict) else {}
    filename = options.get("output_filename") or _default_output_name(conversion.target_format)
    size_bytes: int | None = None
    if conversion.output_available and conversion.output_storage_key is not None:
        try:
            size_bytes = object_store.size(conversion.output_storage_key)
        except Exception:  # noqa: BLE001 - a missing/expired object just leaves size unknown.
            size_bytes = None

    download = {
        "available": conversion.output_available,
        # True iff validation failed — the 05 §2 download-acknowledgment gate (enforced in M24).
        "requires_ack": conversion.validation_status == "failed",
        "filename": filename,
        "size_bytes": size_bytes,
    }
    return {
        "conversion_id": conversion.conversion_id,
        "conversion_report": conversion_report.body,
        "validation_report": validation_report.body if validation_report is not None else None,
        "download": download,
    }


def _first(reports: Sequence[Report], kind: str) -> Report | None:
    return next((r for r in reports if r.kind == kind), None)
