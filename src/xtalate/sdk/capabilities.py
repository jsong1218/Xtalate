"""Capability declaration data model (MASTER_SPEC Part 3 §4.1).

These types live in the SDK — not in ``capabilities`` (the registry package) — so a plugin
can declare what it can read/write without importing the machinery that assembles the
matrix (Revision 1.2; Part 3 §4.1). The registry (``xtalate.capabilities``) validates
the ``fields`` keys against the canonical schema paths and answers queries; the *shape*
declared here is all a parser/exporter author needs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CapabilityLevel(StrEnum):
    FULL = "full"  # Format can always express this field.
    PARTIAL = "partial"  # Format can express it under conditions (see notes).
    NONE = "none"  # Format cannot express it.


class FieldCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: CapabilityLevel
    # Human-readable condition, surfaced verbatim in Conversion Report "Reason" text.
    notes: str | None = None


class FormatCapabilities(BaseModel):
    """One format's read- or write-side capability declaration (Part 3 §4.1). The
    parser/exporter returns this from ``capabilities()``; the registry assembles the
    per-format declarations into the Capability Matrix."""

    model_config = ConfigDict(extra="forbid")

    format_id: str  # Matches ParserPlugin/ExporterPlugin.format_id.
    format_name: str
    direction: Literal["read", "write"]
    # Keyed by canonical field path (Part 2 §3), or a "<category>.*" wildcard (§4.1).
    fields: dict[str, FieldCapability] = Field(default_factory=dict)
    max_frames: int | None = None  # None = unlimited; 1 = single-structure format.
    # Canonical paths that MUST be present to write this format (write side only). Drives Recovery.
    required_fields: list[str] = Field(default_factory=list)
    # Whether the format can express an open (non-periodic) cell, `pbc=(F,F,F)` (write side). Drives
    # the ✳`non_periodic` option of the `missing_lattice` recovery scenario (Part 4 §3.3): a lattice
    # a periodic-only target *requires* can be fabricated as an open box only for a target that can
    # say "not periodic" — extXYZ yes, POSCAR never. An explicit, machine-readable flag rather than
    # a prose reading of the `cell.pbc` note (DECISIONS.md D35). Absent/False = fully-periodic only.
    allows_open_boundaries: bool = False
    # The constraint `kind` values this format can represent (write side; Part 2 §3.6, Part 4 §3.3).
    # When `dynamics.constraints` is PARTIAL, this is the machine-readable subset the
    # `constraint_representation` recovery `project` choice keeps (the remainder → `removed`) — e.g.
    # POSCAR declares `["selective_dynamics"]`. Empty for a format that represents no constraints.
    representable_constraint_kinds: list[str] = Field(default_factory=list)
    native_coordinate_system: Literal["cartesian", "fractional", "both"]
    lossy_notes: list[str] = Field(default_factory=list)  # Format-level caveats -> Warnings.
    # Declared decimal precision per canonical field path (write side) — the machine-readable
    # generalization of ``lossy_notes`` that feeds the Validation Engine's representational-bound
    # tolerance (Part 5 §4.2). ``None`` for a field, or an absent field, means *full* precision
    # (the exporter round-trips it exactly, e.g. POSCAR's ``repr(float)`` Cartesian coordinates ->
    # bound 0). An integer *d* means the field is written with *d* decimals -> a per-component
    # representational bound the tolerance formula scales by ``k_warn``/``k_fail``. Additive to the
    # frozen declaration (DECISIONS.md D24); exporters that don't declare it validate at full
    # precision, which is the honest default for the v0.1 formats.
    numeric_precision: dict[str, int | None] = Field(default_factory=dict)
