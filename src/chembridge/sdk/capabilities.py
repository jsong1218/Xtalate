"""Capability declaration data model (MASTER_SPEC Part 3 §4.1).

These types live in the SDK — not in ``capabilities`` (the registry package) — so a plugin
can declare what it can read/write without importing the machinery that assembles the
matrix (Revision 1.2; Part 3 §4.1). The registry (``chembridge.capabilities``) validates
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
    native_coordinate_system: Literal["cartesian", "fractional", "both"]
    lossy_notes: list[str] = Field(default_factory=list)  # Format-level caveats -> Warnings.
