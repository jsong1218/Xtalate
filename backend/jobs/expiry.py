"""Interactive-recovery expiry — a paused job's TTL resolves to a refusal (Part 6 §3.2, M23).

A job paused in ``awaiting_recovery`` carries an ``expires_at`` horizon (the ``running →
awaiting_recovery`` edge stamps it, capped by the input's own expiry). When that horizon passes with
no resume, the pause resolves to a **refused** conversion — ``refusal.code = "RECOVERY_REQUIRED"``,
never a silently applied default. This is Part 4 §3.2's bright line made operational: refusal is the
only default that neither fabricates data nor silently discards real data, so a timeout can never
choose a fabricative or selective-reductive option on the user's behalf.

Two entry points, one core:

* :func:`expire_due_job` resolves one due job — persists the refused Conversion Report, sets the
  job's error envelope, and transitions ``awaiting_recovery → expired``.
* :func:`sweep_expired` walks the whole worklist (every paused job past its horizon) for a future
  scheduled sweeper (Revision 1.4's minute-cadence sweep); :func:`expire_if_due` resolves a single
  job lazily, which is how Tier 0 drives expiry — on the next poll of a paused job (no background
  process required for the no-services tier).

The refused report is **synthesised from the pause's own stored draft**, not recomputed by
re-running the convert. That makes expiry byte-independent by construction: an expired job resolves
to ``refused`` even if its input bytes are already gone — the categorical guarantee the bright line
demands, and one a re-parse (which fails once the upload has expired) could not make.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from backend.db import as_utc, utcnow
from backend.jobs.logging import log_event
from backend.jobs.runner import _new_id
from backend.models import ErrorBody

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.db import Repository
    from backend.db.models import Job

#: The refusal an expired pause carries (Part 4 §3.2). Worded as a refusal *for want of a decision*,
#: never as if a default were applied (the expired-state honesty rule, Part 7 §2.4: the conversion
#: was refused because no recovery choice was made).
EXPIRY_REFUSAL_MESSAGE = (
    "the interactive recovery window expired before the required decisions were supplied; "
    "the conversion was refused rather than applying any default"
)


def sweep_expired(
    repository: Repository, settings: Settings, *, now: datetime | None = None
) -> list[str]:
    """Resolve every paused job past its horizon to ``expired`` (the scheduled sweep, Part 6 §3.2).

    Returns the ids of the jobs expired. ``now`` is injectable so a test drives the clock
    deterministically (pass a time past the pauses' horizons); it defaults to :func:`utcnow`.
    """
    when = now or utcnow()
    expired: list[str] = []
    for job in repository.list_awaiting_recovery():
        if _is_due(job.expires_at, when):
            expire_due_job(job, repository, settings, now=when)
            expired.append(job.job_id)
    return expired


def expire_if_due(
    job: Job, repository: Repository, settings: Settings, *, now: datetime | None = None
) -> Job:
    """Expire ``job`` iff it is paused and past its horizon, returning the (possibly updated) job.

    The lazy path Tier 0 relies on: a poll of a paused job resolves it if its TTL has passed, so no
    background sweeper is needed for the no-services tier. A non-paused or not-yet-due job is
    returned unchanged. Idempotent: a job already ``expired`` is not paused, so it is a no-op.
    """
    if job.state != "awaiting_recovery":
        return job
    when = now or utcnow()
    if not _is_due(job.expires_at, when):
        return job
    expire_due_job(job, repository, settings, now=when)
    reloaded = repository.get_job(job.job_id)
    return reloaded if reloaded is not None else job


def expire_due_job(job: Job, repository: Repository, settings: Settings, *, now: datetime) -> None:
    """Resolve one paused job to ``expired`` with a refused Conversion Report (Part 6 §3.2).

    Persists a refused conversion (``conversion_status="refused"``, no output bytes and no output
    key — an expired pause produces no file, only the record of why) and its Conversion Report,
    sets the job's error envelope to a ``RECOVERY_REQUIRED`` body (the surface the future UI renders
    the "refused because no choice was made" statement from, Part 7 §2.4), then transitions
    ``awaiting_recovery → expired`` — clearing the paused block, which no longer applies.
    """
    from backend.db.models import Conversion, Report

    block = job.recovery or {}
    request = job.request if isinstance(job.request, dict) else {}
    request_id = request.get("request_id")
    file_id = request.get("file_id")

    report_body = build_expired_report(block, now=now)
    conversion_id = _new_id("cnv")
    target = report_body.get("target") or {}
    source = report_body.get("source") or {}
    repository.add_conversion(
        Conversion(
            conversion_id=conversion_id,
            job_id=job.job_id,
            source_file_id=file_id if isinstance(file_id, str) else None,
            source_format=source.get("format_id"),
            target_format=target.get("format_id") or request.get("target_format_id") or "unknown",
            output_storage_key=None,
            output_available=False,
            conversion_status="refused",
            validation_status=None,
        )
    )
    repository.add_report(
        Report(
            report_id=_new_id("rep"),
            job_id=job.job_id,
            conversion_id=conversion_id,
            kind="conversion",
            body=report_body,
        )
    )
    error_body = ErrorBody(
        code="RECOVERY_REQUIRED",
        message=EXPIRY_REFUSAL_MESSAGE,
        details={"conversion_id": conversion_id},
        request_id=request_id if isinstance(request_id, str) else "unknown",
        documentation_url=f"{settings.docs_base_url}#recovery_required",
    ).model_dump(mode="json")
    repository.transition_job(
        job.job_id, "expired", finished_at=now, error=error_body, clear_recovery=True
    )
    log_event("job.expired", job_id=job.job_id, kind=job.kind, request_id=request_id)


def build_expired_report(recovery_block: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Synthesise the refused Conversion Report for an expired pause from its stored block.

    The pause persisted its pre-flight ``draft_report`` and the **computed** unresolved scenarios
    (Part 6 §3.2). The refused final report is that draft re-stamped ``stage="final"``,
    ``status="refused"`` with a ``RECOVERY_REQUIRED`` refusal whose ``unresolved_scenarios`` are the
    block's own, de-enriched back to bare option codes (the refusal-body shape of Part 4 §4). No
    re-parse is involved, so it holds even once the input bytes are gone. Round-tripped through
    :class:`~xtalate.conversion.report.ConversionReport` so the stored body is a valid report.
    """
    from xtalate.conversion.report import ConversionReport

    draft = dict(recovery_block.get("draft_report") or {})
    draft["report_id"] = _new_id("rep")
    draft["stage"] = "final"
    draft["status"] = "refused"
    draft["created_at"] = now.isoformat()
    draft["refusal"] = {
        "code": "RECOVERY_REQUIRED",
        "message": EXPIRY_REFUSAL_MESSAGE,
        "unresolved_scenarios": _bare_scenarios(recovery_block),
    }
    return ConversionReport.model_validate(draft).model_dump(mode="json")


def _bare_scenarios(recovery_block: dict[str, Any]) -> list[dict[str, Any]]:
    """De-enrich the block's ``unresolved_scenarios`` back to the refusal-body shape (Part 4 §4).

    The pause enriched each option code into ``{choice, parameters_schema?}`` for the prompt; the
    refusal body carries bare code strings, so ``options`` collapses back to the ``choice`` list —
    nothing added, nothing dropped, so the honest computed list survives into the refusal verbatim.
    """
    bare: list[dict[str, Any]] = []
    for scenario in recovery_block.get("unresolved_scenarios") or []:
        bare.append(
            {
                "scenario": scenario.get("scenario"),
                "path": scenario.get("path"),
                "detail": scenario.get("detail"),
                "options": [
                    o["choice"]
                    for o in scenario.get("options") or []
                    if isinstance(o, dict) and "choice" in o
                ],
            }
        )
    return bare


def _is_due(expires_at: datetime | None, now: datetime) -> bool:
    """Whether a paused job's horizon has passed. A job with no horizon is never swept (defensive —
    the pause edge always stamps one, so this only guards a malformed row)."""
    horizon = as_utc(expires_at)
    return horizon is not None and horizon <= now
