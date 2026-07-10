"""The Validation Report — exact schema (MASTER_SPEC Part 5 §3).

Deliberately mirrors the Conversion Report's conventions (Part 4 §2) — identifier style, ISO-8601
UTC timestamps, machine-code discipline, severity vocabulary — so the two render side-by-side in
the API and UI with no adapter logic. One :class:`CheckResult` per executed or *skipped* check
from the §2 catalog (a skipped check is reported, never omitted: an absent result would leave a
reader guessing whether fidelity was verified or forgotten). The aggregate ``status`` is the worst
individual check outcome.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from chembridge.sdk import ParseIssue


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckResult(_Model):
    check_id: str  # Stable machine code from Part 5 §2, e.g. "positions_rmsd".
    status: str  # Literal["pass", "warn", "fail", "skipped"] — see STATUS_ORDER.
    paths: list[str] = Field(default_factory=list)  # Canonical field paths examined.
    # Check-specific measurements, e.g. {"rmsd_ang": 3.2e-13, "frames_compared": 1}.
    measured: dict[str, JsonValue] = Field(default_factory=dict)
    # The effective thresholds used (§4), e.g. {"warn_ang": 1e-5, "fail_ang": 1e-3,
    # "representational_bound_ang": 0.0}; None for exact/discrete checks.
    tolerance_applied: dict[str, JsonValue] | None = None
    message: str  # Human-readable outcome, specific and quantitative.
    skip_reason: str | None = None  # Populated iff status="skipped".


class ValidationReport(_Model):
    report_id: str  # UUID.
    conversion_report_id: str  # Links to the ConversionReport this validates (Part 4 §2).
    created_at: str  # ISO 8601 UTC.
    # Literal["passed", "passed_with_warnings", "failed"] — worst CheckResult determines it.
    status: str
    checks: list[CheckResult] = Field(default_factory=list)
    # The full profile in force (§4): name + every effective threshold, so the report is
    # self-contained and re-thresholdable later (Part 5 §4.5).
    tolerance_profile: dict[str, JsonValue] = Field(default_factory=dict)
    # Warnings raised while re-parsing the output (Part 3 §5): an output that parses only with
    # warnings is itself a finding.
    reparse_issues: list[ParseIssue] = Field(default_factory=list)
    schema_version: str  # Canonical schema version used for the diff.
