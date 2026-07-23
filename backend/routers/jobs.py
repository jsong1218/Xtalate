"""The async job endpoints — submit (202) and poll (200) under one envelope (MASTER_SPEC Part 6 §3).

``POST /v1/inspect``, ``POST /v1/convert``, and ``POST /v1/validate`` (slice 4) each create a
``queued`` job, enqueue it, and return its :class:`~backend.jobs.envelope.JobEnvelope` at ``202``;
``GET /v1/jobs/{job_id}`` returns the same envelope on every poll, with an optional long-poll
``?wait=<s>`` (capped at 30). Under the Tier 0 inline queue a submitted job is already ``completed``
by the time the response is built, so the first poll is effectively synchronous — the near-sync
ergonomics the uniform-202 contract targets (§3.1). The endpoints hold no scientific logic: they
validate the request, persist a job, and hand a ``job_id`` to the queue.

Submit-time checks give fast, spec-shaped errors (``404``/``410`` on a lost file, ``422`` on an
unknown target) *in addition to* the worker's dequeue-precondition check (``queued → failed``),
which still catches a file that expires in the race between submit and run.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import anyio
from fastapi import APIRouter, Depends, Query, Request, status

from backend.config import Settings
from backend.db import Repository, utcnow
from backend.db.models import Job
from backend.deps import (
    get_job_queue,
    get_object_store,
    get_registry,
    get_repository,
    get_settings,
)
from backend.errors import ApiError
from backend.jobs.envelope import JobEnvelope
from backend.jobs.expiry import expire_if_due
from backend.jobs.logging import log_event
from backend.jobs.queue import JobQueue
from backend.jobs.result import build_job_result
from backend.jobs.state_machine import is_terminal
from backend.models import (
    ConvertRequest,
    InspectRequest,
    RecoveryResumeRequest,
    RevalidateRequest,
)
from backend.storage import ObjectStore
from xtalate.capabilities import Registry

router = APIRouter()

#: Hard ceiling on the long-poll wait (Part 6 §2, §3.1). A client asking for more is clamped, never
#: refused — the contract is "up to 30 s", and holding a request open longer risks proxy timeouts.
MAX_WAIT_SECONDS = 30.0

#: How often the long-poll re-reads the job row while waiting. Coarse enough not to hammer the DB,
#: fine enough that a completed small job returns promptly.
_POLL_INTERVAL_SECONDS = 0.1


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else "unknown"


def _require_live_upload(repository: Repository, file_id: str) -> None:
    """Fast submit-time file check: ``404`` if unknown, ``410`` if its bytes have expired (§2)."""
    upload = repository.get_upload(file_id)
    if upload is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="FILE_NOT_FOUND",
            message=f"No uploaded file {file_id!r}.",
        )
    from backend.db import as_utc, utcnow

    expires_at = as_utc(upload.expires_at)
    if upload.bytes_deleted or (expires_at is not None and expires_at < utcnow()):
        raise ApiError(
            status_code=status.HTTP_410_GONE,
            code="FILE_EXPIRED",
            message=f"Uploaded file {file_id!r} has expired.",
        )


def _registry_fingerprint(registry: Registry) -> str:
    """A stable fingerprint of the parser registry — an upgraded/added parser changes it (§2).

    Part of the inspect idempotency key because a new or upgraded parser can legitimately change the
    Discovery output, so re-inspecting after a plugin install must do real work, not return a stale
    job. Built from the xtalate version + the sorted set of parser format ids (a plugin adding an
    eighth format flips the fingerprint).
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        pkg = version("xtalate")
    except PackageNotFoundError:  # pragma: no cover - non-installed tree only
        pkg = "0.0.0"
    format_ids = ",".join(sorted(p.format_id for p in registry.parsers()))
    return f"{pkg}|{format_ids}"


def _inspect_idempotency_key(body: InspectRequest, registry: Registry) -> str:
    """``(file_id, format_override, registry version)`` → a stable key (§2 idempotent inspect)."""
    raw = f"{body.file_id}|{body.format_override or ''}|{_registry_fingerprint(registry)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _job_envelope(job: Job, repository: Repository, object_store: ObjectStore) -> JobEnvelope:
    """Project a job onto the envelope, attaching its completion result (if any)."""
    result = build_job_result(job, repository, object_store)
    return JobEnvelope.from_row(job, result=result)


@router.post("/inspect", response_model=JobEnvelope, status_code=status.HTTP_202_ACCEPTED)
def inspect(
    body: InspectRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    registry: Registry = Depends(get_registry),
    job_queue: JobQueue = Depends(get_job_queue),
) -> JobEnvelope:
    """Run the Discovery Engine on an uploaded file — idempotent per (file, override, registry)."""
    _require_live_upload(repository, body.file_id)

    key = _inspect_idempotency_key(body, registry)
    existing = repository.find_job_by_idempotency_key(key)
    if existing is not None:
        # Same file + override + registry: return the existing job's envelope, do no new work (§2).
        return _job_envelope(existing, repository, object_store)

    job_id = uuid.uuid4().hex
    repository.add_job(
        Job(
            job_id=job_id,
            kind="inspect",
            state="queued",
            idempotency_key=key,
            request={
                "file_id": body.file_id,
                "format_override": body.format_override,
                "request_id": _request_id(request),
            },
        )
    )
    job_queue.enqueue(job_id)
    return _job_envelope(_reload(repository, job_id), repository, object_store)


@router.post("/convert", response_model=JobEnvelope, status_code=status.HTTP_202_ACCEPTED)
def convert(
    body: ConvertRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    registry: Registry = Depends(get_registry),
    job_queue: JobQueue = Depends(get_job_queue),
) -> JobEnvelope:
    """Submit a conversion (Part 6 §2.1). A refusal is a completed job, not an error (§1)."""
    _require_live_upload(repository, body.file_id)

    writable = {e.format_id for e in registry.exporters()}
    if body.target_format_id not in writable:
        raise ApiError(
            status_code=422,  # literal, not status.HTTP_422_* (deprecated upstream; see errors.py)
            code="UNKNOWN_FORMAT",
            message=f"No writer for target format {body.target_format_id!r}.",
            details={"writable_formats": sorted(writable)},
        )

    job_id = uuid.uuid4().hex
    repository.add_job(
        Job(
            job_id=job_id,
            kind="convert",
            state="queued",
            request={
                "file_id": body.file_id,
                "target_format_id": body.target_format_id,
                "options": body.options.model_dump(mode="json"),
                "request_id": _request_id(request),
            },
        )
    )
    job_queue.enqueue(job_id)
    return _job_envelope(_reload(repository, job_id), repository, object_store)


@router.post("/validate", response_model=JobEnvelope, status_code=status.HTTP_202_ACCEPTED)
def validate(
    body: RevalidateRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    job_queue: JobQueue = Depends(get_job_queue),
) -> JobEnvelope:
    """Re-threshold a stored conversion under a new tolerance profile (Part 6 §2, Part 5 §4.5).

    A query over persisted reports, not a re-parse — available after byte expiry by construction.
    ``404`` if the conversion record is unknown (or has passed report retention).
    """
    conversion = repository.get_conversion(body.conversion_id)
    if conversion is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONVERSION_NOT_FOUND",
            message=f"No conversion {body.conversion_id!r}.",
        )

    job_id = uuid.uuid4().hex
    repository.add_job(
        Job(
            job_id=job_id,
            kind="validate",
            state="queued",
            request={
                "conversion_id": body.conversion_id,
                "tolerance_profile": body.tolerance_profile,
                "request_id": _request_id(request),
            },
        )
    )
    job_queue.enqueue(job_id)
    return _job_envelope(_reload(repository, job_id), repository, object_store)


@router.post("/jobs/{job_id}/recovery", response_model=JobEnvelope, tags=["jobs"])
def resume_recovery(
    job_id: str,
    body: RecoveryResumeRequest,
    request: Request,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    job_queue: JobQueue = Depends(get_job_queue),
    settings: Settings = Depends(get_settings),
) -> JobEnvelope:
    """Resume an ``awaiting_recovery`` convert job with the client's choices (Part 6 §3.2).

    Validates the job is paused (``404`` unknown, ``409 JOB_NOT_AWAITING_RECOVERY`` otherwise) and
    every choice against the paused block's *offered* options (``422 INVALID_RECOVERY_CHOICE`` with
    ``offered_choices``), then merges them into the request as ``origin: "user"`` decisions and
    re-enqueues. The ``awaiting_recovery → running`` edge is the worker's; a resume that resolves
    only some scenarios pauses again for the rest. The endpoint holds no scientific logic — the
    Recovery Engine still computes and applies the choice on the worker.

    A resume that arrives after the pause's TTL is a ``409`` naming the ``expired`` state: the job
    is expired-if-due first, so a client racing the deadline learns the pause is gone rather than
    resuming a job whose input bytes may already have expired (Part 6 §3.2, §5).
    """
    job = repository.get_job(job_id)
    if job is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="JOB_NOT_FOUND",
            message=f"No job {job_id!r}.",
        )
    job = expire_if_due(job, repository, settings)
    if job.state != "awaiting_recovery":
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="JOB_NOT_AWAITING_RECOVERY",
            message=f"Job {job_id!r} is {job.state!r}, not awaiting recovery.",
            details={"state": job.state},
        )

    _validate_recovery_choices(job.recovery, body.choices)
    merged = _merge_recovery_choices(job.request, body.choices)
    repository.set_job_request(job_id, merged)
    job_queue.enqueue(job_id)
    return _job_envelope(_reload(repository, job_id), repository, object_store)


@router.post("/jobs/{job_id}/cancel", response_model=JobEnvelope, tags=["jobs"])
def cancel_job(
    job_id: str,
    request: Request,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings),
) -> JobEnvelope:
    """Cancel a job, moving it to the terminal ``cancelled`` state (Part 6 §3.2, §5).

    ``404 JOB_NOT_FOUND`` for an unknown id. Cancelling an already-``cancelled`` job is an
    **idempotent** ``200`` — a retried cancel is not an error. Any *other* terminal state
    (``completed``, ``failed``, ``expired``) is a ``409 JOB_ALREADY_TERMINAL`` naming the state,
    because that outcome is already recorded and cancellation must not overwrite it. An already
    ``expired`` pause has resolved to a *refusal*, which a cancel must never erase: the
    ``expire_if_due`` below makes an overdue pause terminal *before* this check, so a cancel that
    lost the race to the deadline learns the job expired rather than silently cancelling it.

    A cancellable job (``queued``, ``running``, ``awaiting_recovery``) transitions straight to
    ``cancelled`` with a finish timestamp and its recovery block cleared. Cancellation produces **no
    output file and no Conversion Report** — it is an abandonment, not a refusal, so the envelope
    carries neither a ``result`` nor an ``error`` body, only the terminal state.

    Under the Tier 0 inline queue a submitted job is already terminal by the time a client could
    call this, so the state actually cancellable here is ``awaiting_recovery`` (a paused convert).
    Cooperative interruption of a genuinely mid-run job on the Tier 1 RQ worker — a checkpointed
    stop at a frame-chunk boundary — is a follow-up on this same endpoint (Part 6 §5's stated cut),
    never a change to this contract: the state machine already holds the ``running → cancelled``
    edge, so that work attaches as a *caller*, not a new edge (**P6**).
    """
    job = repository.get_job(job_id)
    if job is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="JOB_NOT_FOUND",
            message=f"No job {job_id!r}.",
        )
    job = expire_if_due(job, repository, settings)
    if job.state == "cancelled":
        return _job_envelope(job, repository, object_store)  # idempotent re-cancel (200)
    if is_terminal(job.state):
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="JOB_ALREADY_TERMINAL",
            message=f"Job {job_id!r} is {job.state!r} and cannot be cancelled.",
            details={"state": job.state},
        )
    repository.transition_job(job_id, "cancelled", finished_at=utcnow(), clear_recovery=True)
    log_event("job.cancelled", job_id=job_id, kind=job.kind, request_id=_request_id(request))
    return _job_envelope(_reload(repository, job_id), repository, object_store)


def _offered_choices(recovery_block: dict[str, Any] | None) -> dict[str, list[str]]:
    """Map each offered scenario code → its offered ``choice`` strings, from the paused block."""
    offered: dict[str, list[str]] = {}
    for scenario in (recovery_block or {}).get("unresolved_scenarios") or []:
        code = scenario.get("scenario")
        if isinstance(code, str):
            offered[code] = [
                o["choice"]
                for o in scenario.get("options") or []
                if isinstance(o, dict) and "choice" in o
            ]
    return offered


def _validate_recovery_choices(
    recovery_block: dict[str, Any] | None, choices: dict[str, dict[str, Any]]
) -> None:
    """Reject any choice the paused job did not offer (``422 INVALID_RECOVERY_CHOICE``, Part 6 §6).

    A client can only pick from the *computed* option lists the pause served — an unknown scenario
    or an unoffered choice is refused with the scenario and its ``offered_choices``, never coerced.
    """
    offered = _offered_choices(recovery_block)
    for scenario_code, decision in choices.items():
        valid = offered.get(scenario_code)
        if valid is None:
            raise ApiError(
                status_code=422,  # literal, not status.HTTP_422_* (deprecated upstream, errors.py)
                code="INVALID_RECOVERY_CHOICE",
                message=f"{scenario_code!r} is not an unresolved scenario for this job.",
                details={"scenario": scenario_code, "offered_choices": []},
            )
        chosen = decision.get("choice") if isinstance(decision, dict) else None
        if chosen not in valid:
            raise ApiError(
                status_code=422,
                code="INVALID_RECOVERY_CHOICE",
                message=f"{chosen!r} is not an offered choice for {scenario_code!r}.",
                details={"scenario": scenario_code, "offered_choices": valid},
            )


def _merge_recovery_choices(
    request: dict[str, Any], choices: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Merge interactive choices into a job's request and mark it a user-supplied resume.

    Accumulates over ``options.recovery_choices`` (so a second resume adds to the first — a partial
    answer followed by the rest), and sets the ``recovery_resumed`` marker the worker reads to label
    the applied Assumptions ``origin: "user"`` (Part 4 §2). Returns a new dict; input is unchanged.
    """
    merged = dict(request)
    options = dict(merged.get("options") or {})
    recovery_choices = dict(options.get("recovery_choices") or {})
    recovery_choices.update(choices)
    options["recovery_choices"] = recovery_choices
    merged["options"] = options
    merged["recovery_resumed"] = True
    return merged


@router.get("/jobs/{job_id}", response_model=JobEnvelope, tags=["jobs"])
async def get_job(
    job_id: str,
    repository: Repository = Depends(get_repository),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings),
    wait: float = Query(
        default=0.0,
        ge=0.0,
        description="Long-poll: seconds to wait for a terminal state before returning (max 30).",
    ),
) -> JobEnvelope:
    """Poll a job's envelope. With ``?wait=<s>`` (capped 30), hold until the job is terminal.

    A poll of a paused job past its TTL expires it (``awaiting_recovery → expired``, resolving to a
    refused conversion) before projecting — the lazy sweep Tier 0 relies on, so the no-services tier
    needs no background sweeper for the expiry-to-refusal rule to hold (Part 6 §3.2).
    """
    job = repository.get_job(job_id)
    if job is None:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="JOB_NOT_FOUND",
            message=f"No job {job_id!r}.",
        )
    job = expire_if_due(job, repository, settings)

    if wait > 0 and not is_terminal(job.state):
        deadline = anyio.current_time() + min(wait, MAX_WAIT_SECONDS)
        while not is_terminal(job.state) and anyio.current_time() < deadline:
            await anyio.sleep(_POLL_INTERVAL_SECONDS)
            reloaded = repository.get_job(job_id)
            if reloaded is None:  # pragma: no cover - a job row does not vanish mid-poll.
                break
            job = expire_if_due(reloaded, repository, settings)

    return _job_envelope(job, repository, object_store)


def _reload(repository: Repository, job_id: str) -> Job:
    """Re-read a job after enqueue (inline queue may have already advanced it to terminal)."""
    job = repository.get_job(job_id)
    if job is None:  # pragma: no cover - the row was just written in this request.
        raise ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Job vanished immediately after creation.",
        )
    return job
