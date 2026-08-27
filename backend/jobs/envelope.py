"""The job envelope — the uniform wire shape every async operation is polled through (Part 6 §3.2).

``POST /v1/inspect``, ``/v1/convert``, and ``/v1/validate`` all return this one shape, and
``GET /v1/jobs/{job_id}`` returns it again on every poll (`06 §3.1`, the uniform-202 contract). The
envelope is a *transport* model the service owns (like the error envelope), distinct from the
library's report models — but its ``result`` **embeds those reports verbatim** (`06` preamble): a
completed convert job's ``result.conversion_report`` is the ``ConversionReport`` dumped with
``mode="json"``, no reshaping. That verbatim-ness is the M22 cut line's first non-negotiable.

The envelope is a projection of the persisted :class:`~backend.db.models.Job` row (plus, for a
completed job, its stored reports). :meth:`JobEnvelope.from_row` is the one place that projection
lives, so the ORM columns and the wire fields never drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from backend.db.models import Job


class JobChildRef(BaseModel):
    """One batch child's projection inside its parent's envelope (Part 6 §3, v1.5 M58).

    A transport-only summary — the ``job_id`` to navigate to the **ordinary** child record, the
    ``file_id`` it converts, and its current ``state`` — so a client can see at a glance which
    children are done and which (e.g. a paused ``awaiting_recovery`` child) still need attention.
    The child's own envelope/record is the full record; this is a link, never a copy of its
    report (the aggregate embeds reports verbatim only in the completed ``result``).
    """

    job_id: str
    file_id: str | None = None
    state: str


class JobProgress(BaseModel):
    """Coarse progress for a running job (Part 6 §3.2).

    ``phase`` names the pipeline stage the worker last entered (``"parsing"``, ``"converting"``,
    ``"validating"``, …); ``frames_processed``/``frames_total`` are the v0.3 chunked engine's frame
    counters when a streamed operation exposes them, ``None`` otherwise. M22 stamps the phase at
    each stage boundary; live frame counters attach at the same seam with no shape change (**P6**).
    """

    phase: str | None = None
    frames_processed: int | None = None
    frames_total: int | None = None


def _iso(value: datetime | None) -> str | None:
    """ISO 8601 UTC, matching the report timestamp convention (`06 §1`); ``None`` stays ``None``."""
    return value.isoformat() if value is not None else None


class JobEnvelope(BaseModel):
    """The full job envelope returned on submit and on every poll (Part 6 §3.2).

    ``result`` is the kind-specific completion payload (``None`` until the job completes):
    ``{discovery_report}`` for inspect, ``{conversion_id, conversion_report, validation_report,
    download}`` for convert, ``{validation_report}`` for validate — each embedding the library's
    report models verbatim. ``error`` is the error envelope's inner body (the same shape a non-2xx
    response carries) for a ``failed`` job, ``None`` otherwise. ``awaiting_recovery`` detail is an
    M23 addition to this same model — absent here, never a reshaping of what M22 established.
    """

    job_id: str
    kind: str
    state: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    expires_at: str | None = None
    progress: JobProgress = Field(default_factory=JobProgress)
    #: The interactive-recovery block for a job paused in ``awaiting_recovery`` (Part 6 §3.2, M23):
    #: ``{draft_report, unresolved_scenarios: [{scenario, path, detail, options: [{choice,
    #: parameters_schema?}]}]}``. ``None`` in every other state. The future UI renders its recovery
    #: prompt from this block alone, so its completeness is the M23 pause deliverable.
    awaiting_recovery: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    #: A ``batch_convert`` parent's fanned-out children (``job_id`` + ``file_id`` + ``state``), so
    #: the batch record is navigable in every state — including which child is paused. Empty for
    #: every other job kind (v1.5 M58).
    children: list[JobChildRef] = Field(default_factory=list)

    @classmethod
    def from_row(
        cls,
        job: Job,
        *,
        result: dict[str, Any] | None = None,
        children: list[JobChildRef] | None = None,
    ) -> JobEnvelope:
        """Project a persisted :class:`~backend.db.models.Job` (+ its ``result``) onto the envelope.

        ``result`` is assembled by the caller (runner/router) from the job's stored reports, because
        it is kind-specific and embeds verbatim report bodies the envelope model does not model.
        The ``awaiting_recovery`` block is the persisted ``job.recovery`` column, served back
        verbatim while paused (it is set only on that edge and cleared when the job leaves it).
        ``children`` is the batch parent's child projection, assembled by the same caller from the
        persisted child rows (empty for non-batch jobs).
        """
        progress = JobProgress.model_validate(job.progress) if job.progress else JobProgress()
        return cls(
            job_id=job.job_id,
            kind=job.kind,
            state=job.state,
            created_at=_iso(job.created_at) or "",
            updated_at=_iso(job.updated_at) or "",
            started_at=_iso(job.started_at),
            finished_at=_iso(job.finished_at),
            expires_at=_iso(job.expires_at),
            progress=progress,
            awaiting_recovery=job.recovery,
            result=result,
            error=job.error,
            children=list(children or []),
        )
