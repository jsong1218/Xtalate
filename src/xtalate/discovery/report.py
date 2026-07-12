"""The Discovery Report — exact schema (MASTER_SPEC Part 3 §6.2).

The ✓/✗ inventory the Information Discovery Engine produces: for a sniffed-and-parsed file,
which canonical fields it contains, each annotated with the *read-side* capability of the
detected format (so a reader sees not just "present" but "and this format could express it").
The ``fields`` list is **complete over the canonical scientific leaf paths** (Part 2 §3.3–§3.7
plus ``frame.time`` and ``trajectory.timestep``) — every one appears exactly once, present or
absent, so "not shown" can never be mistaken for "not checked" (§6.3). Root metadata containers
and carried-through user data are summarized in ``structure``/``extras`` instead, since their
contents are format-specific rather than a fixed schema of leaf paths.

Emitted verbatim by the API's ``/v1/inspect`` (Part 6) and the CLI's ``inspect`` (Appendix A);
the CLI renders it as a terminal inventory, never a parallel DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from xtalate.sdk import CapabilityLevel, ParseIssue


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldPresenceEntry(_Model):
    path: str  # Canonical field path, e.g. "dynamics.velocities".
    status: (
        str  # Literal["present", "absent", "mixed"] — "mixed" mirrors PresenceMap (Part 2 §3.11).
    )
    # Populated only when status="mixed": the frame indices where the field is present.
    present_frames: list[int] | None = None
    format_capability: CapabilityLevel  # Read-side capability of the detected format for this path.
    detail: str | None = None  # e.g. "2 frames × 3 atoms, Cartesian (Å)".


class DiscoveryReport(_Model):
    file: dict[str, Any]  # { filename, size_bytes, sha256 }.
    # { format_id, format_name, confidence, sniff_evidence: [{format_id, confidence}, ...] }.
    format: dict[str, Any]
    structure: dict[str, Any]  # { frame_count, atom_count, species: [...] }.
    fields: list[FieldPresenceEntry] = Field(default_factory=list)  # One entry per leaf path.
    extras: list[str] = Field(
        default_factory=list
    )  # Carried-through custom_* / simulation.extra keys.
    issues: list[ParseIssue] = Field(default_factory=list)  # Warnings from the parse (Part 3 §5).
    schema_version: str  # Of the Canonical Object produced.
