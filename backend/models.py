"""Wire models the *service* owns — not the library's report models.

The library's report models (``DiscoveryReport``, ``ConversionReport``, ``ValidationReport``)
cross the wire **verbatim** — no DTOs, no renames (Part 6 preamble; v0.5 standing rule 2). The
models here are the ones the transport itself introduces and the library has no opinion about:
the error envelope, the limits view, and the health/readiness response. They live in ``backend``
precisely because they are API concerns, not canonical-model concerns.
"""

from __future__ import annotations

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
    registered dependency checks (database, object storage — populated in M24); ``status`` is
    ``"ok"`` only when every check passed, ``"degraded"`` otherwise, and the endpoint returns
    ``503`` on ``degraded`` so an orchestrator's probe fails correctly.
    """

    status: str
    environment: str
    version: str
    checks: dict[str, ReadinessCheck] = Field(default_factory=dict)
