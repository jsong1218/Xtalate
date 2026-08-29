"""Wire models the *service* owns — not the library's report models.

The library's report models (``DiscoveryReport``, ``ConversionReport``, ``ValidationReport``)
cross the wire **verbatim** — no DTOs, no renames (Part 6 preamble; v0.5 standing rule 2). The
models here are the ones the transport itself introduces and the library has no opinion about:
the error envelope, the limits view, and the health/readiness response. They live in ``backend``
precisely because they are API concerns, not canonical-model concerns.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from backend.tolerance import validate_tolerance_profile
from xtalate.conversion.batch import BatchError, BatchTallies


class ErrorBody(BaseModel):
    """The inner ``error`` object of the single non-2xx envelope (Part 6 §6)."""

    #: Stable machine string, e.g. ``UNKNOWN_FORMAT``, ``MALFORMED_REQUEST`` (never localized).
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

    #: An unknown profile name or a malformed custom table is a request error, caught here so it
    #: renders as ``400 MALFORMED_REQUEST`` (Part 6 §6) with the library's own actionable message —
    #: rather than as a job that is accepted, queued, and only then fails.
    _check_tolerance = field_validator("tolerance_profile")(validate_tolerance_profile)


class ConvertRequest(BaseModel):
    """``POST /v1/convert`` body (Part 6 §2.1)."""

    file_id: str
    target_format_id: str
    options: ConvertOptions = Field(default_factory=ConvertOptions)


class BatchFileOverride(BaseModel):
    """Per-file override of the shared batch options (``POST /v1/batch/convert``, v1.5 M58).

    Mirrors the library's per-source override (``xtalate.conversion.batch.SourceOverride``) field
    for field, with the wire's own recovery-choice shape (the ``{scenario: {choice, parameters}}"
    dict of :class:`ConvertOptions`, not the CLI's preset strings). Each field *replaces* the
    shared value for that one file; a field left ``None`` inherits the shared option. In
    particular ``recovery_choices`` replaces — never merges — the shared preset list, so one file
    can preset a different decision than the rest of the batch (per-file consent stays per-file).
    ``allow_recovery`` is the wire-only opt-in (the CLI refuses; the API pauses, Part 6 §3.2), so
    it can be flipped off for a single file of an otherwise-interactive batch.
    """

    mode: str | None = None
    recovery_choices: dict[str, dict[str, Any]] | None = None
    tolerance_profile: str | dict[str, Any] | None = None
    acknowledge_loss: bool | None = None
    acknowledge_parse_warnings: bool | None = None
    allow_recovery: bool | None = None

    #: Same request-time check as :class:`ConvertOptions` — an unusable per-file profile is a
    #: submit error, never a job the caller must poll to discover was doomed.
    _check_tolerance = field_validator("tolerance_profile")(validate_tolerance_profile)


class BatchConvertRequest(BaseModel):
    """``POST /v1/batch/convert`` body (Part 6 §2, v1.5 M58) — N uploaded ``file_id``s, one
    target, shared options, and optional per-file overrides.

    The wire manifest is deliberately just this: **ordered** ``file_ids`` (processing and report
    order), one target, the shared :class:`ConvertOptions`, and per-file overrides. It has **no
    fields** for selection, splitting, deduplication, or rebalancing — aggregation, never curation
    (roadmap §11; the library manifest's scope refusal, carried to the wire). The API fans out at
    the job layer: the parent creates one ordinary ``convert`` job per ``file_id`` and aggregates
    their persisted reports verbatim; it never re-implements the batch semantics (Part 6 preamble).
    """

    file_ids: list[str]
    target_format_id: str
    options: ConvertOptions = Field(default_factory=ConvertOptions)
    #: Per-file overrides keyed by ``file_id``; a key naming a file outside ``file_ids`` is a
    #: malformed request (``400 MALFORMED_REQUEST``), never silently ignored.
    overrides: dict[str, BatchFileOverride] = Field(default_factory=dict)


class BatchConvertEntry(BaseModel):
    """One child's terminal outcome inside the aggregate (Part 6 §3, v1.5 M58).

    A thin transport record — ``child_job_id`` + the per-file outcome — that **embeds the child's
    ``ConversionReport``/``ValidationReport`` verbatim** (the persisted bodies, unreshaped) so the
    same file converted alone and inside a batch serializes byte-identically. ``error`` mirrors the
    library's per-file failure record (``BatchError``: ``{code, message}``), present only for a
    ``failed`` child (a parse error, an expired input); a refusal is *not* an error — it is a
    completed conversion whose embedded report says so, exactly as on the single-file path.
    """

    file_id: str
    child_job_id: str
    status: Literal["converted", "refused", "failed"]
    conversion_report: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    error: BatchError | None = None


class BatchConvertResult(BaseModel):
    """The aggregate result of a completed ``batch_convert`` job (Part 6 §3, v1.5 M58).

    **Counts, never restatements**: the reused library ``BatchTallies``/``LabelPresence`` (so the
    wire tallies are byte-identical to the CLI's ``run_batch`` on the same inputs) plus the
    per-child entries embedding the existing reports verbatim. ``note`` is the dataset-level
    statement slot, mirroring ``BatchReport.note``; the HTTP surface has no assemble/fan-out
    notes to make, so it stays ``None`` unless a future additive mode earns one. A ``BatchReport``
    embeds a path-based manifest, which is wrong for the wire — this thin model is the transport's
    own (D217); it adds **zero** schema fields and **no** second report schema.
    """

    tallies: BatchTallies
    entries: list[BatchConvertEntry] = Field(default_factory=list)
    note: str | None = None


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


class AssumptionPreview(BaseModel):
    """One Assumption a paused job *would* record for a previewed choice (Part 6 §3.2 preview).

    The ``description`` is the engine's own sentence, verbatim — byte-identical to what the resume
    will record — so the UI shows a user the exact provenance they are creating before they confirm
    it (P4). ``scenario``/``choice``/``parameters`` echo the decision the sentence describes.
    """

    scenario: str
    choice: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    description: str


class RecoveryPreviewResponse(BaseModel):
    """``POST /v1/jobs/{job_id}/recovery/preview`` body — the byte-exact Assumption preview.

    Additive to the Part 6 §3.2 recovery surface (a new endpoint ⇒ non-breaking): the client sends
    the same ``choices`` shape as a resume, and gets back the Assumptions the resume *would*
    record — without advancing the job or writing any output. Recovery is all-or-nothing, so an
    incomplete choice set yields no ``previews`` and instead names the scenarios still
    ``unresolved`` — the UI renders each card's exact provenance only once its decisions are made.
    """

    previews: list[AssumptionPreview] = Field(default_factory=list)
    #: Scenario codes still owed a decision; non-empty iff ``previews`` is empty (all-or-nothing).
    unresolved: list[str] = Field(default_factory=list)


class RevalidateRequest(BaseModel):
    """``POST /v1/validate`` body — re-threshold a stored conversion under a new profile (§2, §4.5).

    Not a re-parse: it re-evaluates the conversion's **stored** measured values against a different
    tolerance profile, so it works even after the source/output bytes have expired (reports outlive
    bytes). ``404`` if the conversion is unknown or its record has passed report retention.
    """

    conversion_id: str
    tolerance_profile: str | dict[str, Any] = "default"

    #: Same request-time check as :class:`ConvertOptions` — one rule for one wire field.
    _check_tolerance = field_validator("tolerance_profile")(validate_tolerance_profile)


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
    #: The report window as **days** — populated only when no sub-day override is active. ``None``
    #: means either an ``report_retention_hours`` override is in force (read that instead) or, when
    #: ``report_retention_hours`` is *also* ``None``, indefinite retention (self-hosted default).
    report_retention_days: int | None
    #: The report window as **hours**, set only when a sub-day override is configured (the hosted
    #: demo uses 1). Exactly one of ``report_retention_hours`` / ``report_retention_days`` is
    #: non-null unless retention is indefinite, in which case both are ``None``. Additive field
    #: (v1.2) — an older client that reads only ``report_retention_days`` still sees a correct
    #: (``None`` = "not in days") value.
    report_retention_hours: int | None


class DownloadInfo(BaseModel):
    """The ``download`` object on a conversion record (Part 6 §4.4).

    ``available`` goes false once the output bytes pass their lifecycle window — the record and its
    reports remain retrievable, so a stale link renders as "expired", not "not found" (reports-
    outlive-bytes). ``requires_ack`` mirrors the download endpoint's failed-validation gate, so a UI
    can pre-warn before the ``409``. ``size_bytes``/``expires_at`` are ``None`` once unavailable.
    """

    available: bool
    requires_ack: bool
    filename: str
    size_bytes: int | None = None
    expires_at: str | None = None


class ConversionRecordResponse(BaseModel):
    """``GET /v1/conversions/{conversion_id}`` — the durable record, both reports verbatim (§4.4).

    Served from persisted rows alone, so it resolves after the output (or input) bytes have expired:
    the reports embed exactly what the library produced (no DTO reshaping), and ``download`` tells
    the client whether the bytes are still fetchable. ``validation_report`` is ``None`` for a
    refused conversion (no output ⇒ no validation) or while validation is still running.
    """

    conversion_id: str
    created_at: str
    source: dict[str, Any]
    target: dict[str, Any]
    conversion_report: dict[str, Any]
    validation_report: dict[str, Any] | None = None
    download: DownloadInfo


class HistoryItem(BaseModel):
    """One ``items[]`` entry from ``GET /v1/history`` (Part 6 §4.4).

    A compact projection for the list view: source/target formats + filenames (the report's source
    minus hashes), the two statuses, and the ``summary_counts`` chips
    (``{preserved, removed, assumptions, warnings}``, counted from the conversion report — the
    counts the v0.6 UI renders per ``07 §4``). ``file_id`` is present only while the source upload
    is still live, which is what lets a UI offer a re-convert without a fresh upload (``07 §2.6``).
    """

    conversion_id: str
    created_at: str
    source: dict[str, Any]
    target: dict[str, Any]
    conversion_status: str | None
    validation_status: str | None = None
    summary_counts: dict[str, int]
    file_id: str | None = None


class GeometrySource(BaseModel):
    """Which bytes a geometry response projects (v1.6 M59-S1) — the wire identity of the source.

    A faithful projection answers *what was parsed*, so the viewer shows a format-named origin
    rather
    than a silent blob. ``filename`` is the upload name for a ``file_id``/``side=source`` read and
    the conventional output name for ``side=output``; it may be ``None`` only when none exists.
    """

    format_id: str
    filename: str | None = None


class GeometryFrame(BaseModel):
    """One projected frame's geometry (v1.6 M59-S1) — positions + per-frame cell as nested lists.

    ``positions`` is the ``(N, 3)`` Cartesian array as a nested JSON list (the canonical array wire
    form, Part 2 §1). ``cell`` is the frame's ``(3, 3)`` lattice as a nested list, and ``null`` when
    the source carried none — absence renders as absence (P3), never a fabricated box. ``index`` is
    the frame's **absolute** 0-based position in the whole trajectory, so a ranged read is
    addressable even though the frame arrived inside a ``[start, end)`` slice.
    """

    index: int
    positions: list[list[float]]
    cell: list[list[float]] | None = None


class GeometryResponse(BaseModel):
    """``GET /v1/files/{id}/geometry`` and ``GET /v1/conversions/{id}/geometry`` (v1.6 M59).

    A **wire projection** of the Canonical Object, assembled from the parsed ``FrameStream`` — the
    geometric subset a molecular viewer needs, never a second canonical artifact and never a report
    (Part 6 §7 additive read-only geometry). Load-bearing rules:

    * **Absence renders as absence (P3).** ``species``/``positions``/``cell`` hold only what the
      source stated; a ``cell = None`` source answers ``cell: null``, and ``cell`` is ``null`` on
      any frame whose lattice the source did not provide — nothing is zero-filled or fabricated.
    * **No bonds.** The Canonical Model holds no bonds, so this projection carries none — an atomic
      coordination bond is a *display* heuristic (D234), never file content and never served here.
    * **Ranged by frame index.** ``frames`` holds the exact requested ``[start, end)`` slice (or
      frame 0 when ``frames`` is omitted); ``frame_index_base`` names the absolute index of its
      first member and ``frame_count`` the whole object's total, so a scrubber knows both where a
      page sits and how far it could go.
    * ``species``/``cell`` are the object-level shape: the atom-count-invariant symbols and frame-
      0's lattice (or ``null``), read from the parsed stream before any range slice.
    """

    source: GeometrySource
    species: list[str]
    cell: list[list[float]] | None = None
    frame_index_base: int = 0
    frame_count: int
    frames: list[GeometryFrame] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    """``GET /v1/history`` — a page of :class:`HistoryItem` plus the opaque next-page cursor.

    ``next_cursor`` is ``None`` on the last page; otherwise it is passed back as ``?cursor=`` to
    fetch the following page. Pagination is keyset over ``(created_at, conversion_id)`` descending
    (newest first), so a record added between page fetches never shifts or duplicates an item the
    way an offset would — the cursor names a fixed point in the ordering, not a position count.
    """

    items: list[HistoryItem]
    next_cursor: str | None = None


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
