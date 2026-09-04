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


#: The ``Assumption.scenario`` code a *repair* records (v1.7 M64; D249). A repair is not a
#: recovery scenario — it is "recovery the user initiates" — so its assumption rows carry this
#: single stable discriminator with the operation name in ``choice`` and the complete parameters
#: in ``parameters``; consumers render those rows as the report's user-requested "repairs"
#: section, distinct from format-forced ``removed``/``supplied`` (D250).
REPAIR_SCENARIO = "repair"


class ReportWarning(_Model):
    code: str  # Stable machine code, e.g. "COORDINATE_REPRESENTATION_CHANGED".
    message: str
    # ParseIssue echo (Part 3 §5 rule 5), lossy_notes/capability caveat, exporter transform,
    # or a repair's transformative-hazard statement (v1.7 M64, D251).
    source: Literal["parse", "capability", "export", "repair"]


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

    @property
    def repairs(self) -> list[Assumption]:
        """The report's user-requested **repairs section** (v1.7 M64; D250) — the ``Assumption``
        rows a user-initiated repair recorded, in application order.

        A derived view over the existing ``assumptions`` list (no separate report object, no
        extra serialized field — a report without repairs is byte-identical to one before this
        version): a repair records one row with ``scenario == REPAIR_SCENARIO``, the operation
        name in ``choice``, and the complete recorded parameters in ``parameters`` — the data
        the reproducibility harness needs to re-derive the repaired object from the report
        alone. Repairs never fabricate or remove a canonical path, so they produce no
        ``supplied``/``removed`` entries of their own; their transformative-loss statements ride
        ``warnings`` with ``source="repair"``."""
        return [a for a in self.assumptions if a.scenario == REPAIR_SCENARIO]

    @property
    def repair_warnings(self) -> list[ReportWarning]:
        """The repair hazard statements (source="repair") in report order (v1.7 M64; D251)."""
        return [w for w in self.warnings if w.source == "repair"]
