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

from backend.models import BatchConvertEntry, BatchConvertResult
from backend.records import default_output_name

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
    if job.kind == "batch_convert":
        return _batch_convert_result(job, repository)
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
    filename = options.get("output_filename") or default_output_name(conversion.target_format)
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


def _batch_convert_result(job: Job, repository: Repository) -> dict[str, Any] | None:
    """The aggregate completion payload for a ``batch_convert`` parent (Part 6 §3, v1.5 M58).

    Rebuilt from the **persisted child rows on every poll** — the one source of truth, so the
    worker's completion and every later poll agree byte for byte. Children are ordinary
    ``convert`` jobs whose reports ride the same verbatim path as a solo conversion; the
    aggregate is the library's own ``BatchTallies``/``LabelPresence`` (reused, never re-declared,
    so the wire tallies are byte-identical to the CLI's ``run_batch`` on the same inputs) plus
    thin per-child entries embedding the reports verbatim — counts and embeddings only, never a
    digest (the second-report-schema failure mode). ``None`` whenever a manifest file has no
    terminal child — the parent only completes when every child is terminal, so this guards a
    malformed row rather than a normal poll.
    """
    # The label→canonical-path map is the library's own (``xtalate.conversion.batch._LABEL_PATHS``
    # — kept private there, imported here deliberately so the wire tally can never drift from the
    # CLI's: one source of truth for which preserved paths mean "the output carries the label").
    from xtalate.conversion.batch import _LABEL_PATHS, BatchTallies, LabelPresence

    request = job.request
    file_ids = request.get("file_ids") or []
    children = {
        c.request.get("file_id"): c
        for c in repository.get_child_jobs(job.job_id)
        if isinstance(c.request, dict)
    }
    entries: list[BatchConvertEntry] = []
    for file_id in file_ids:
        child = children.get(file_id)
        if child is None:
            return None  # a manifest file was never fanned out — the parent is not complete.
        entry = _batch_child_entry(child, repository, file_id)
        if entry is None:
            return None  # a child is not terminal — the parent is not complete.
        entries.append(entry)
    converted = [e for e in entries if e.status == "converted"]
    presence = LabelPresence()
    for entry in converted:
        report = entry.conversion_report or {}
        preserved = {p.get("path") for p in report.get("preserved") or []}
        for label, path in _LABEL_PATHS.items():
            if path in preserved:
                setattr(presence, label, getattr(presence, label) + 1)
    tallies = BatchTallies(
        total=len(entries),
        converted=len(converted),
        refused=sum(1 for e in entries if e.status == "refused"),
        failed=sum(1 for e in entries if e.status == "failed"),
        label_presence=presence,
    )
    result = BatchConvertResult(tallies=tallies, entries=entries, note=None)
    return result.model_dump(mode="json")


def _batch_child_entry(
    child: Job, repository: Repository, file_id: str
) -> BatchConvertEntry | None:
    """One child's terminal outcome as a :class:`BatchConvertEntry` (v1.5 M58), or ``None`` if
    the child is not terminal (the parent must not complete then). ``file_id`` is the manifest's
    own id — the authoritative label, not a re-derivation from the child's request.

    ``completed`` → the child's persisted Conversion/Validation reports embedded **verbatim**,
    status ``refused`` iff the report says so (a refusal is a completed job, exactly as solo).
    ``expired`` → the expiry path persisted a refused Conversion Report (``RECOVERY_REQUIRED``),
    so the entry is a ``refused`` embedding that report — an expired pause is a refusal, never a
    silent default. ``failed`` → the child's own error-envelope body, projected to the library's
    per-file ``BatchError`` ``{code, message}`` shape. ``cancelled`` → an abandonment (no report,
    no output): a ``failed`` entry whose ``BatchError`` names ``JOB_CANCELLED``.
    """
    from xtalate.conversion.batch import BatchError

    if child.state == "completed":
        reports = repository.get_reports_for_job(child.job_id)
        conversion = _first(reports, "conversion")
        if conversion is None:
            return None  # defensive: a completed convert always persisted its report.
        validation = _first(reports, "validation")
        return BatchConvertEntry(
            file_id=file_id,
            child_job_id=child.job_id,
            status="refused" if conversion.body.get("status") == "refused" else "converted",
            conversion_report=conversion.body,
            validation_report=validation.body if validation is not None else None,
        )
    if child.state == "expired":
        reports = repository.get_reports_for_job(child.job_id)
        conversion = _first(reports, "conversion")
        if conversion is None:
            return None  # defensive: expiry always persisted its refusal report.
        return BatchConvertEntry(
            file_id=file_id,
            child_job_id=child.job_id,
            status="refused",
            conversion_report=conversion.body,
        )
    if child.state == "failed":
        error = child.error or {}
        return BatchConvertEntry(
            file_id=file_id,
            child_job_id=child.job_id,
            status="failed",
            error=BatchError(
                code=error.get("code", "JOB_FAILED"),
                message=error.get("message", "the child conversion job failed"),
            ),
        )
    if child.state == "cancelled":
        return BatchConvertEntry(
            file_id=file_id,
            child_job_id=child.job_id,
            status="failed",
            error=BatchError(
                code="JOB_CANCELLED",
                message="the child job was cancelled before it produced a conversion",
            ),
        )
    return None  # queued/running/awaiting_recovery — the parent must not complete.
