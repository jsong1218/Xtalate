"""Wire models the *service* owns — not the library's report models.

The library's report models (``DiscoveryReport``, ``ConversionReport``, ``ValidationReport``)
cross the wire **verbatim** — no DTOs, no renames (Part 6 preamble; v0.5 standing rule 2). The
models here are the ones the transport itself introduces and the library has no opinion about:
the error envelope, the limits view, and the health/readiness response. They live in ``backend``
precisely because they are API concerns, not canonical-model concerns.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """The inner ``error`` object of the single non-2xx envelope (Part 6 §6)."""

    #: Stable machine string, e.g. ``UNKNOWN_FORMAT``, ``INVALID_REQUEST`` (never localized).
    code: str
    #: Human-readable, one-line explanation. Safe to log; never carries scientific file content.
    message: str
    #: Structured, machine-usable specifics (offending field, allowed values, …). ``{}`` when none.
    details: dict[str, object] = Field(default_factory=dict)
    #: Correlates this response with server logs; echoed in the ``X-Request-ID`` header.
    request_id: str
    #: Deep link to the reference entry for ``code`` (built from ``docs_base_url``).
    documentation_url: str


class ErrorEnvelope(BaseModel):
    """The whole non-2xx body: ``{ "error": { … } }`` (Part 6 §6).

    Every error path — a raised :class:`~backend.errors.ApiError`, a FastAPI request-validation
    failure, an unexpected exception, an unmatched route — renders through this one shape, so a
    client writes exactly one error-handling branch. Retrofitting an envelope under thirty
    endpoints is the rewrite M21 exists to avoid, so the envelope-first rule holds from endpoint 1.
    """

    error: ErrorBody


class UploadResponse(BaseModel):
    """``POST /v1/upload`` — the stored file's handle (Part 6 §2.2).

    M22 ships a *stub* upload (whole-body read, direct-to-storage) so the job pipeline has a
    ``file_id`` to convert; M24 replaces the endpoint body with streaming + size enforcement, under
    this same response. ``expires_at`` is the byte-lifecycle horizon (§5); reports outlive it (M24).
    """

    file_id: str
    filename: str
    size_bytes: int
    sha256: str
    expires_at: str


class InspectRequest(BaseModel):
    """``POST /v1/inspect`` body — run the Information Discovery Engine on an uploaded file."""

    file_id: str
    #: Override the Format Sniffer (Part 3 §6.1); part of the idempotency key (§2), so a different
    #: override is a different inspect and always does real work.
    format_override: str | None = None


class ConvertOptions(BaseModel):
    """``POST /v1/convert`` ``options`` (Part 6 §2.1) — names match ``04_Conversion_Engine.md``."""

    mode: str = "permissive"
    #: Preset recovery choices keyed by scenario code; each ``{choice, parameters}`` (Part 4 §3.3).
    #: They land in the report as ``origin: "preset"``.
    recovery_choices: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: Opt into **interactive** recovery (Part 6 §3.2, M23): when set, a conversion whose recovery
    #: scenarios have no supplied preset **pauses** to ``awaiting_recovery`` (the client resumes via
    #: ``POST /v1/jobs/{job_id}/recovery``) instead of refusing. Default ``False`` keeps the
    #: preset-only contract a pipeline or the CLI relies on — an unresolved scenario is a completed
    #: refused job at HTTP 200, never a pause it must poll (the CLI-refuses / API-pauses split of
    #: the fabricative bright line, Appendix A vs. Part 6 §3.2). The pause is only ever reachable
    #: when a client explicitly asks to answer the questions interactively.
    allow_recovery: bool = False
    acknowledge_loss: bool = False
    acknowledge_parse_warnings: bool = False
    #: Named profile (``default``/``strict``/``loose``) or a custom tolerance table (Part 5 §4.4).
    tolerance_profile: str | dict[str, Any] = "default"
    output_filename: str | None = None


class ConvertRequest(BaseModel):
    """``POST /v1/convert`` body (Part 6 §2.1)."""

    file_id: str
    target_format_id: str
    options: ConvertOptions = Field(default_factory=ConvertOptions)


class RecoveryResumeRequest(BaseModel):
    """``POST /v1/jobs/{job_id}/recovery`` body (Part 6 §2, §3.2) — resume a paused convert job.

    ``choices`` maps a scenario code to the user's decision — ``{choice, parameters}`` — the same
    shape as :attr:`ConvertOptions.recovery_choices`, but supplied *interactively* after the job
    paused rather than up front. The endpoint validates each choice against the paused job's own
    **offered** options before merging it in (an unoffered scenario or choice is
    ``422 INVALID_RECOVERY_CHOICE``), so a resumed choice lands in the report as ``origin: "user"``.
    A resume that resolves only some scenarios pauses again for the rest (Part 6 §3.2).
    """

    choices: dict[str, dict[str, Any]] = Field(default_factory=dict)


class RevalidateRequest(BaseModel):
    """``POST /v1/validate`` body — re-threshold a stored conversion under a new profile (§2, §4.5).

    Not a re-parse: it re-evaluates the conversion's **stored** measured values against a different
    tolerance profile, so it works even after the source/output bytes have expired (reports outlive
    bytes). ``404`` if the conversion is unknown or its record has passed report retention.
    """

    conversion_id: str
    tolerance_profile: str | dict[str, Any] = "default"


class LimitsResponse(BaseModel):
    """``GET /v1/limits`` — every Part 6 §5 constraint, config-driven (Revisions 1.4, 1.5).

    A client reads the rules before hitting them. In M21 these are surfaced from configuration;
    the surfaces that *enforce* them (upload streaming, rate limiting, the recovery pause) wire
    to the same values in M23/M24, so the advertised number and the enforced number are one thing.
    """

    max_upload_bytes: int
    max_frames: int
    max_concurrent_jobs: int
    rate_limit_per_minute: int
    upload_retention_hours: int
    output_retention_hours: int
    awaiting_recovery_ttl_minutes: int
    #: ``None`` = indefinite retention (self-hosted default).
    report_retention_days: int | None


class ReadinessCheck(BaseModel):
    """One dependency's readiness result, reported by ``GET /v1/health?ready=true``."""

    #: ``True`` iff the dependency answered within the check.
    ok: bool
    #: One-line human detail (backend kind, error summary) — never secrets or connection strings.
    detail: str | None = None


class HealthResponse(BaseModel):
    """``GET /v1/health`` — liveness always; readiness when ``?ready=true``.

    Liveness (``status == "ok"``, ``checks`` empty) proves the process is up. Readiness runs the
    registered dependency checks (database and object storage, registered in M21); ``status`` is
    ``"ok"`` only when every check passed, ``"degraded"`` otherwise, and the endpoint returns
    ``503`` on ``degraded`` so an orchestrator's probe fails correctly.
    """

    status: str
    environment: str
    version: str
    checks: dict[str, ReadinessCheck] = Field(default_factory=dict)
