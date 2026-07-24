"""The worker's job body — execute one job by calling the library exactly as the CLI does.

:func:`execute_job` is the whole of what a worker does with a dequeued job: move it ``running``,
drive the same engines the CLI drives (`Appendix A`) over the uploaded bytes, persist the resulting
reports verbatim, and move it ``completed`` — or ``failed`` on a transport/parse fault. Two rules
from Part 6 are load-bearing and each has a test:

* **A refusal is a completed job.** ``ConversionEngine.convert`` returns a ``ConversionReport`` with
  ``status="refused"`` (never raises) when a needed recovery choice was not supplied; that is a
  *completed* job at HTTP 200, its refusal report the result — not a ``failed`` job (`06 §1`).
* **A crash is a failed job, never a stuck ``running`` row.** Every exception after the job goes
  ``running`` is caught and turned into a ``failed`` transition carrying a structured error envelope
  in ``job.error``. (A true process kill mid-chunk is the reaper's job, M25; within the process,
  the try/except is the guarantee the done-means tests.)

Dependencies are injected (:func:`execute_job`) so the inline queue can pass the app's shared
adapters and a test can pass its own; :func:`run_job_from_env` is the module-level entry RQ enqueues
in the separate worker process, where it rebuilds the adapters from the environment (Part 9 §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from backend.db import as_utc, utcnow
from backend.jobs.logging import log_event
from backend.jobs.recovery import RecoveryPause
from backend.models import ErrorBody

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db import Repository
    from backend.db.models import Job
    from backend.storage import ObjectStore
    from xtalate.capabilities import Registry


class _JobFailure(Exception):
    """A pre-run precondition loss (e.g. the upload expired) — a ``queued → failed`` outcome.

    Carries the error-envelope body to persist in ``job.error``. Distinct from an in-run exception
    (which fails from ``running``): this fires before the job starts, at the dequeue-precondition
    check the state diagram draws as ``queued → failed`` (Part 6 §3.2).
    """

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        super().__init__(body.get("code", "FAILED"))


def _error_body(
    settings: Settings, code: str, message: str, details: dict[str, Any], request_id: str | None
) -> dict[str, Any]:
    """Build the error-envelope inner body stored in ``job.error`` (the non-2xx body's shape)."""
    return ErrorBody(
        code=code,
        message=message,
        details=details,
        request_id=request_id or "unknown",
        documentation_url=f"{settings.docs_base_url}#{code.lower()}",
    ).model_dump(mode="json")


def _read_bytes(object_store: ObjectStore, key: str) -> bytes:
    """Materialize an object's bytes. M22 reads the whole file (Tier 0 sizes); the streaming
    convert path (frame-chunked, `M12`) wires through here in a later increment without a shape
    change — the object store already yields chunks (**P6**)."""
    with object_store.open(key) as chunks:
        return b"".join(chunks)


def execute_job(
    job_id: str,
    *,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
) -> None:
    """Run one job to a terminal state, persisting every transition (Part 6 §3.2)."""
    job = repository.get_job(job_id)
    if job is None:
        log_event("job.missing", job_id=job_id)
        return
    request_id = job.request.get("request_id") if isinstance(job.request, dict) else None
    # A freshly-queued job, or one being resumed from awaiting_recovery (Part 6 §3.2, M23), is
    # runnable. An inline double-enqueue or a redelivered RQ message for an already-running/terminal
    # job is a no-op, never a re-run (idempotent execution).
    if job.state not in ("queued", "awaiting_recovery"):
        log_event("job.skip", job_id=job_id, state=job.state, request_id=request_id)
        return

    resuming = job.state == "awaiting_recovery"
    if resuming:
        # Resume: go running *first*, clearing the paused block, so a lost input now fails from
        # running (awaiting_recovery → failed is not a legal edge; the pause TTL was capped by the
        # upload's expiry, so a live resume normally finds live bytes). started_at is left as the
        # original run's — the job began working when it first ran, not when it was answered.
        repository.transition_job(
            job_id, "running", progress={"phase": "parsing"}, clear_recovery=True
        )
        log_event("job.resumed", job_id=job_id, kind=job.kind, request_id=request_id)

    try:
        upload = _resolve_preconditions(job, repository, settings, request_id)
    except _JobFailure as failure:
        # A fresh job fails from queued (the dequeue-precondition edge); a resumed job is already
        # running, so this same failure is a legal running → failed. Both land in job.error.
        repository.transition_job(job_id, "failed", finished_at=utcnow(), error=failure.body)
        log_event(
            "job.failed",
            job_id=job_id,
            state="failed",
            code=failure.body["code"],
            request_id=request_id,
        )
        return

    if not resuming:
        repository.transition_job(
            job_id, "running", started_at=utcnow(), progress={"phase": "parsing"}
        )
        log_event("job.running", job_id=job_id, kind=job.kind, request_id=request_id)

    try:
        _dispatch(job, upload, repository, object_store, registry, settings)
    except RecoveryPause as pause:
        # Interactive recovery (Part 6 §3.2): the convert needs a choice the client did not preset
        # and asked to answer interactively — pause, don't refuse. Persist the awaiting_recovery
        # block and a TTL horizon (capped by the input's own expiry so a paused job never outlives
        # the bytes it needs to resume, Revision 1.4). Expiry-to-refusal enforcement is M23 slice 3.
        repository.transition_job(
            job_id,
            "awaiting_recovery",
            progress={"phase": "recovery"},
            recovery=pause.block,
            expires_at=_awaiting_recovery_deadline(upload, settings),
        )
        log_event("job.awaiting_recovery", job_id=job_id, kind=job.kind, request_id=request_id)
        return
    except Exception as exc:  # noqa: BLE001 - every in-run fault becomes a failed job, not a 500.
        body = _failure_body(exc, settings, request_id)
        repository.transition_job(job_id, "failed", finished_at=utcnow(), error=body)
        log_event(
            "job.failed", job_id=job_id, state="failed", code=body["code"], request_id=request_id
        )
        return

    # A cancel may have raced this run (Tier 1 RQ: a client cancels a genuinely ``running`` job
    # while the worker is mid-dispatch). The cancel endpoint has already moved the row to the
    # terminal ``cancelled`` state, so ``running → completed`` is now illegal — and, worse, this
    # dispatch may have persisted a conversion, its reports, and output bytes, contradicting the
    # binding rule that a cancelled conversion produces *no output and no Conversion Report* (Part 6
    # §3.2). If the job is no longer ``running`` we abandon: discard whatever this run persisted and
    # leave the terminal record the cancel wrote. (Under the Tier 0 inline queue this never fires —
    # a submitted job is terminal before a client could cancel it.)
    current = repository.get_job(job_id)
    if current is not None and current.state != "running":
        keys = repository.discard_job_products(job_id)
        for key in keys:
            object_store.delete(key)
        log_event(
            "job.cancel_race_abandoned",
            job_id=job_id,
            state=current.state,
            request_id=request_id,
        )
        return

    repository.transition_job(job_id, "completed", finished_at=utcnow(), progress={"phase": "done"})
    log_event("job.completed", job_id=job_id, kind=job.kind, request_id=request_id)


def _resolve_preconditions(
    job: Job, repository: Repository, settings: Settings, request_id: str | None
) -> Any:
    """Load and validate the inputs a job needs *before* it starts (``queued → failed`` on loss).

    inspect/convert need their upload present and its bytes unexpired; validate needs its stored
    conversion. A lost precondition is a ``_JobFailure`` (→ ``failed``), never a mid-run crash.
    """
    if job.kind in ("inspect", "convert"):
        file_id = job.request.get("file_id")
        upload = repository.get_upload(file_id) if isinstance(file_id, str) else None
        if upload is None:
            raise _JobFailure(
                _error_body(
                    settings,
                    "FILE_NOT_FOUND",
                    "The uploaded file no longer exists.",
                    {},
                    request_id,
                )
            )
        expires_at = as_utc(upload.expires_at)
        if upload.bytes_deleted or (expires_at is not None and expires_at < utcnow()):
            raise _JobFailure(
                _error_body(
                    settings, "FILE_EXPIRED", "The uploaded file has expired.", {}, request_id
                )
            )
        return upload
    return None  # validate resolves its conversion inside its dispatch (slice 4)


def _failure_body(exc: Exception, settings: Settings, request_id: str | None) -> dict[str, Any]:
    """Map an in-run exception to a structured error-envelope body (Part 6 §6).

    A ``ParseError`` (the file could not be read) surfaces its own stable code — the
    ``PARSE_ERROR``/``UNKNOWN_FORMAT`` of the endpoint table — with the parse issues as details; a
    bad recovery preset is ``INVALID_RECOVERY_CHOICE``; anything else is the ``INTERNAL_ERROR``
    backstop, whose text is generic (the exception may quote content, which must not leak blindly).
    """
    from backend.jobs.revalidate import RevalidateError
    from xtalate.recovery import RecoveryError
    from xtalate.sdk import ParseError

    if isinstance(exc, RevalidateError):
        return _error_body(settings, "VALIDATION_UNAVAILABLE", str(exc), {}, request_id)
    if isinstance(exc, ParseError):
        codes = {issue.code for issue in exc.issues if issue.severity == "error"}
        code = "UNKNOWN_FORMAT" if codes == {"UNKNOWN_FORMAT"} else "PARSE_ERROR"
        message = "; ".join(i.message for i in exc.issues) or "The file could not be parsed."
        details = {
            "issues": [
                {"code": i.code, "severity": i.severity, "message": i.message} for i in exc.issues
            ]
        }
        return _error_body(settings, code, message, details, request_id)
    if isinstance(exc, RecoveryError):
        return _error_body(settings, "INVALID_RECOVERY_CHOICE", str(exc), {}, request_id)
    return _error_body(
        settings,
        "INTERNAL_ERROR",
        "An unexpected error occurred. Quote the request_id when reporting it.",
        {},
        request_id,
    )


# --- per-kind dispatch --------------------------------------------------------------------------


def _dispatch(
    job: Job,
    upload: Any,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
) -> None:
    """Run the kind-specific body. Each persists its reports/conversion; the completion payload is
    assembled later from those rows by :func:`~backend.jobs.result.build_job_result` (one source of
    truth — the persisted state — for both the worker and every poll)."""
    if job.kind == "inspect":
        _run_inspect(job, upload, repository, object_store, registry)
    elif job.kind == "convert":
        _run_convert(job, upload, repository, object_store, registry, settings)
    elif job.kind == "validate":
        _run_validate(job, repository, settings)
    else:
        raise ValueError(f"unknown job kind {job.kind!r}")  # a bug (kinds validated at submit).


def _run_inspect(
    job: Job,
    upload: Any,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
) -> None:
    """Discovery Engine over the uploaded bytes — the ``xtalate inspect`` path (Part 3 §6)."""
    from backend.db.models import Report
    from xtalate.discovery import DiscoveryEngine

    # inspect's ``format_override`` is a per-request parameter (Part 6 §2); it falls back to any
    # override recorded on the upload itself.
    override = job.request.get("format_override") or upload.format_override
    data = _read_bytes(object_store, upload.storage_key)
    report = DiscoveryEngine(registry).discover(
        data, filename=upload.filename, format_override=override
    )
    repository.add_report(
        Report(
            report_id=_new_id("rep"),
            job_id=job.job_id,
            kind="discovery",
            body=report.model_dump(mode="json"),
        )
    )


def _run_convert(
    job: Job,
    upload: Any,
    repository: Repository,
    object_store: ObjectStore,
    registry: Registry,
    settings: Settings,
) -> None:
    """Full conversion — the ``xtalate convert`` path (Part 4): parse (with preset recovery) →
    convert → automatic validation → persist. Reports are stored verbatim; the output bytes go to
    object storage under the new ``conversion_id`` (the record outlives them, M24).

    When the request set ``allow_recovery`` and the conversion refused because a recovery choice
    was not supplied (``RECOVERY_REQUIRED``), this **pauses** instead of persisting the refusal —
    raising :class:`~backend.jobs.recovery.RecoveryPause` for the runner to turn into a ``running →
    awaiting_recovery`` transition (Part 6 §3.2, M23). Every other refusal (a strict-mode
    acknowledgement gate, or the preset-only default when ``allow_recovery`` is unset) is a
    completed refused job exactly as in M22 — the pause is reachable only when the client asked."""
    from backend.db.models import Conversion, Report
    from backend.jobs.recovery import build_awaiting_block, resolve_reference_choices
    from xtalate.conversion import ConversionEngine, parse_with_recovery

    request = job.request
    target_format_id = request["target_format_id"]
    options = request.get("options") or {}
    # ``upload_reference`` choices name a second uploaded file by ``file_id``; the Recovery Engine
    # needs it as a parsed CanonicalObject (the library is filesystem-free), so the worker resolves
    # each reference before the parse/convert consume the choices — the HTTP equivalent of the CLI's
    # ``file=PATH`` injection (Part 4 §3.3). A choice carrying no reference is passed through.
    recovery_choices = resolve_reference_choices(
        options.get("recovery_choices") or {},
        repository=repository,
        object_store=object_store,
        registry=registry,
    )
    allow_recovery = bool(options.get("allow_recovery", False))
    # Resume merges the user's answers into the request and marks them (M23 slice 2); the flag is
    # absent on the initial submit, so preset choices stay ``origin: "preset"``.
    recovery_origin = "user" if request.get("recovery_resumed") else "preset"

    data = _read_bytes(object_store, upload.storage_key)
    parsed = parse_with_recovery(
        registry, data, filename=upload.filename, recovery_choices=recovery_choices
    )
    repository.set_job_progress(job.job_id, {"phase": "converting"})
    engine = ConversionEngine(registry)
    result = engine.convert(
        parsed.canonical,
        source_format_id=parsed.format_id,
        target_format_id=target_format_id,
        source_filename=upload.filename,
        target_filename=options.get("output_filename"),
        mode=options.get("mode", "permissive"),
        recovery_choices=recovery_choices,
        recovery_origin=recovery_origin,
        parse_recovery=parsed,
        acknowledge_loss=options.get("acknowledge_loss", False),
        acknowledge_parse_warnings=options.get("acknowledge_parse_warnings", False),
        tolerance_profile=options.get("tolerance_profile", "default"),
    )

    # Interactive recovery (Part 6 §3.2): a needed-but-unsupplied choice pauses rather than refuses,
    # but only when the client opted in. The draft is the pre-flight preview; the option lists come
    # from the trial convert's refusal (the authoritative, pair-specific computed set).
    refusal = result.report.refusal  # a plain dict body (Part 4 §4), or None when not refused.
    if (
        allow_recovery
        and result.report.status == "refused"
        and isinstance(refusal, dict)
        and refusal.get("code") == "RECOVERY_REQUIRED"
    ):
        draft = engine.preflight(
            parsed.canonical,
            source_format_id=parsed.format_id,
            target_format_id=target_format_id,
            source_filename=upload.filename,
            target_filename=options.get("output_filename"),
            mode=options.get("mode", "permissive"),
        )
        raise RecoveryPause(
            build_awaiting_block(
                draft_report=draft.model_dump(mode="json"),
                refusal=refusal,
            )
        )

    conversion_id = _new_id("cnv")

    # Store the output bytes (unless refused, which produces none). The record row carries the
    # storage key and a byte-expiry horizon; when the output-byte lifecycle sweep clears the bytes
    # (a bucket rule in Tier 1, Part 9 §5.2) the record and its reports still resolve — a download
    # past ``output_expires_at`` is a ``410 OUTPUT_EXPIRED`` while the reports stay retrievable
    # (reports-outlive-bytes). The horizon matches the storage lifecycle window
    # (``output_retention_hours``) so the record's own clock agrees with the platform's sweep.
    output_key: str | None = None
    output_available = False
    output_expires_at: datetime | None = None
    if result.output is not None:
        output_key = f"outputs/{conversion_id}"
        object_store.put(output_key, [result.output])
        output_available = True
        output_expires_at = utcnow() + timedelta(hours=settings.output_retention_hours)

    validation_status = result.validation.status if result.validation else None
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job.job_id,
            source_file_id=upload.file_id,
            source_format=parsed.format_id,
            target_format=target_format_id,
            output_storage_key=output_key,
            output_available=output_available,
            output_expires_at=output_expires_at,
            conversion_status=result.report.status,
            validation_status=validation_status,
        )
    )
    repository.add_report(
        Report(
            report_id=_new_id("rep"),
            job_id=job.job_id,
            conversion_id=conversion_id,
            kind="conversion",
            body=result.report.model_dump(mode="json"),
        )
    )
    if result.validation is not None:
        repository.add_report(
            Report(
                report_id=_new_id("rep"),
                job_id=job.job_id,
                conversion_id=conversion_id,
                kind="validation",
                body=result.validation.model_dump(mode="json"),
            )
        )


def _run_validate(job: Job, repository: Repository, settings: Settings) -> None:
    """Re-threshold a stored Validation Report under a new tolerance profile (slice 4)."""
    from backend.jobs.revalidate import run_revalidate

    run_revalidate(job, repository, settings)


def _default_output_name(format_id: str) -> str:
    """A format-conventional output filename (matches the CLI's ``_emit`` conventions, Part 4)."""
    if format_id in ("poscar", "contcar"):
        return "POSCAR" if format_id == "poscar" else "CONTCAR"
    return f"output.{format_id}"


def _awaiting_recovery_deadline(upload: Any, settings: Settings) -> datetime:
    """When a paused job expires (Part 6 §5, Revision 1.4): ``now + ttl``, **capped by the input's**
    own ``expires_at`` so a paused job can never outlive the persisted bytes it needs to resume.

    A paused convert re-reads and re-parses its upload on resume, so once the input bytes are gone
    the pause is unresolvable — expiring no later than the input keeps the ``awaiting_recovery →
    running`` edge always honourable, and expiring *to a refusal* (slice 3) keeps the line whole."""
    deadline = utcnow() + timedelta(minutes=settings.awaiting_recovery_ttl_minutes)
    upload_expiry = as_utc(getattr(upload, "expires_at", None))
    if upload_expiry is not None and upload_expiry < deadline:
        return upload_expiry
    return deadline


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def run_job_from_env(job_id: str) -> None:
    """Module-level RQ entry point: rebuild the adapters from the environment, then run the job.

    RQ serializes a *function reference* + args onto the queue; the worker process (a different
    process from the API) imports this and calls it, so it cannot share ``app.state`` — it builds
    repository, object store, and registry from :func:`~backend.config.get_settings` (Part 9 §2, the
    environment is the single config source). The inline backend never uses this; it injects the
    app's already-built adapters into :func:`execute_job` directly.
    """
    from backend.config import get_settings
    from backend.db import Repository
    from backend.storage import create_object_store
    from xtalate.registry import default_registry

    settings = get_settings()
    execute_job(
        job_id,
        repository=Repository.from_settings(settings),
        object_store=create_object_store(settings),
        registry=default_registry(),
        settings=settings,
    )
