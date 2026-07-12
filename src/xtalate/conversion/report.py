"""The Conversion Report — exact schema (MASTER_SPEC Part 4 §2).

The structured record of what a conversion kept, dropped, fabricated, transformed, or
assumed — **Preserved / Removed / Supplied / Assumptions / Warnings** (Part 0 §6 plus the
normative `Supplied` addition of §2). One schema serves both the *pre-flight draft* (shown
before conversion; Part 3 §4.3) and the *final report*, distinguished by `stage`, so the
promise and the record are structurally comparable and any divergence is itself a defect the
Validation Engine flags (Part 5).

`Removed` entries each carry their own `reason` — "Reason" is not a separate list (§2).
`Supplied` and `Assumptions` are one-to-(one-or-more): an `Assumption` records the *decision*,
each `SuppliedEntry` the *canonical field that decision wrote* (§2). Every field is a canonical
path (Part 2 §3); these are the vocabulary the completeness invariant (§2) is stated over.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreservedEntry(_Model):
    path: str  # Canonical field path, e.g. "atoms.positions" (Part 2 §3).
    detail: str | None = None  # e.g. "1 frame × 64 atoms", "converted to fractional (Direct)".


class RemovedEntry(_Model):
    path: str  # Canonical path present in the source but absent from the output.
    reason: str  # REQUIRED. From the target FieldCapability.notes, or generated from the level.
    detail: str | None = None  # e.g. "10 frames × 64 atoms × 3 dropped".


class SuppliedEntry(_Model):
    path: str  # Canonical path fabricated by Recovery and written out — absent on the source.
    from_assumption: str  # REQUIRED. The Assumption.id that authorized this value (P4).
    detail: str | None = None  # e.g. "3×3 lattice; pbc (T,T,T) — bounding box of frame 9 + 5 Å".


class Assumption(_Model):
    id: str  # Stable per-report identifier, e.g. "A1".
    scenario: str  # Machine code: "missing_lattice", "frame_selection", … (Part 4 §3).
    choice: str  # Machine code of the selected option: "bounding_box", … (Part 4 §3).
    parameters: dict[str, Any] = Field(default_factory=dict)  # e.g. {"padding_ang": 5.0}.
    origin: Literal["user", "preset"]  # Interactive choice vs pre-supplied in the API call.
    description: str  # Human-readable sentence describing the decision.


class ReportWarning(_Model):
    code: str  # Stable machine code, e.g. "COORDINATE_REPRESENTATION_CHANGED".
    message: str
    # ParseIssue echo (Part 3 §5 rule 5), lossy_notes/capability caveat, or exporter transform.
    source: Literal["parse", "capability", "export"]


class ConversionReport(_Model):
    report_id: str  # UUID.
    stage: Literal["preflight", "final"]
    status: Literal["completed", "awaiting_recovery", "refused"]
    mode: Literal["strict", "permissive"]  # Part 4 §4.
    created_at: str  # ISO 8601 UTC.
    source: dict[str, Any]  # { format_id, filename, sha256, schema_version }.
    target: dict[str, Any]  # { format_id, filename }.
    preserved: list[PreservedEntry] = Field(default_factory=list)
    removed: list[RemovedEntry] = Field(default_factory=list)  # Every entry carries its Reason.
    supplied: list[SuppliedEntry] = Field(default_factory=list)  # [] = nothing fabricated.
    assumptions: list[Assumption] = Field(default_factory=list)  # [] = no fabricated information.
    warnings: list[ReportWarning] = Field(default_factory=list)
    # Populated iff status="refused": { code, message, unresolved_scenarios: [...] } (Part 4 §4).
    refusal: dict[str, Any] | None = None
