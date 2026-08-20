"""Capability declaration data model (MASTER_SPEC Part 3 §4.1).

These types live in the SDK — not in ``capabilities`` (the registry package) — so a plugin
can declare what it can read/write without importing the machinery that assembles the
matrix (Revision 1.2; Part 3 §4.1). The registry (``xtalate.capabilities``) validates
the ``fields`` keys against the canonical schema paths and answers queries; the *shape*
declared here is all a parser/exporter author needs.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    # For a `custom_*` container the format can hold only *specific* keys, the exact writable set
    # keyed by container path (write side; Part 3 §4.2). The machine-readable analogue of
    # `representable_constraint_kinds` for dynamic custom keys: a present key **outside** the set is
    # reported `removed` in pre-flight rather than predicted-preserved and then silently dropped by
    # the exporter — and only the listed keys enter the write plan, so `canonical′` (the Validation
    # Engine's reference) matches what the exporter actually writes. Plain XYZ declares
    # `{"user_metadata.custom_per_frame": ["xyz:comment"]}` — it holds one free-text comment line
    # per frame, so a foreign per-frame key (e.g. an extXYZ `config_type`) is honestly dropped.
    # Empty = no per-key restriction; the container's `fields` level governs every key uniformly.
    writable_custom_keys: dict[str, list[str]] = Field(default_factory=dict)
    # The same restriction expressed as a *name pattern*, for a container whose writable set is
    # open-ended but whose spelling the format constrains (write side; DECISIONS.md D69). Keyed by
    # container path, valued by a regex the key must ``fullmatch`` to be written; a key that fails
    # to match is `removed` exactly as an unlisted key is. extXYZ declares
    # `{"user_metadata.custom_per_atom": r"extxyz:[^:]*"}` — it writes arbitrary columns, so the set
    # cannot be enumerated, but the `Properties=` grammar separates fields with `:` and its parser
    # re-prefixes what it reads, so `extxyz:<name>` is exactly the set that survives write → read
    # under its own name. A container declares a list or a pattern, never both.
    writable_custom_key_pattern: dict[str, str] = Field(default_factory=dict)
    # Canonical path -> the custom key a read parser carries the value under **verbatim** when it
    # cannot map it to the canonical field (read side; DECISIONS.md D18, D151). extXYZ parks
    # `stress` in `custom_per_frame["extxyz:stress"]` rather than `electronic.stress` because its
    # sign convention cannot be reconciled without a source-declared choice. The Validation Engine
    # uses this to find a planned field's value in the re-parse (the carry) so the post-conversion
    # diff can compare it in canonical space instead of false-failing on "missing". Empty = the
    # parser never carries unmapped values for any field (it maps everything it reads).
    carried_field_keys: dict[str, str] = Field(default_factory=dict)
    # Whether this format's representation can hold per-atom **image flags** — the LAMMPS
    # `ix`/`iy`/`iz` wrapped-coordinate bookkeeping — as a structured payload (M46-S3, D176).
    # Read side: the parser carries them specifically to
    # `custom_per_atom['lammps_dump:image_flags']`; write side: the exporter writes them back. The
    # named capability dimension the pre-flight diff reads directly (mirroring a scalar field's
    # PARTIAL/NONE cell): False (the default) = the format cannot hold them, so converting a
    # flag-carrying source to it makes unwrapping impossible and the diff states that consequence
    # before a byte is written. Declared True on `lammps_dump` (read); the incumbent formats
    # (XYZ/extXYZ/POSCAR/CONTCAR/XDATCAR) declare absence by the default.
    holds_image_flags: bool = False
    # Whether this format's representation requires a *declared unit style* to write anything at
    # all (write side; v1.3 M47-S1, D177). A LAMMPS-family target does not define units — its
    # output file is only self-describing when the writer declares an `ITEM: UNITS <style>`
    # header — so exporting to it without a resolved `ambiguous_units` choice is refused, and
    # the declared style is written back (canonical Å/fs/eV converted to the style's basis).
    # Declared True by the LAMMPS dump exporter; the incumbent formats declare absence by the
    # default. The pre-flight diff reads it directly (mirroring the `holds_image_flags`
    # dimension) to fire the write-side `ambiguous_units` scenario — a *target-identity*
    # trigger: a dump needs a style whatever the source carried.
    requires_units_style: bool = False
    # The sign convention of the `electronic.stress` tensor this exporter writes (write side;
    # Part 2 §3.7.1, DECISIONS.md D151). The canonical convention is tension-positive; an exporter
    # whose files carry the opposite (compression-positive, e.g. ASE-native extXYZ) reverses the
    # normalization on write and declares that here — the machine-readable half of the
    # `STRESS_SIGN_CONVENTION_CHANGED` warning, letting validation compare the re-parsed carry
    # back in canonical space. Vocabulary is the `ambiguous_stress_convention` scenario's option
    # codes (Part 4 §3.3) so terminology stays binding: `tension_positive` = written as-is,
    # `ase_sign_convention` = written negated. Irrelevant for an exporter that writes no stress.
    stress_output_convention: Literal["tension_positive", "ase_sign_convention"] = (
        "tension_positive"
    )
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

    @model_validator(mode="after")
    def _check_custom_key_patterns(self) -> FormatCapabilities:
        """A declared pattern must compile, and must not compete with a list for the same container
        (D69). Both are caught at registration rather than at conversion time: a capability
        declaration is data a plugin author writes once, and a broken one should fail loudly when
        the plugin registers, not silently mis-route a key on some later user's conversion."""
        for container, pattern in self.writable_custom_key_pattern.items():
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"writable_custom_key_pattern[{container!r}] is not a valid regex: {exc}"
                ) from exc
            if container in self.writable_custom_keys:
                raise ValueError(
                    f"{container!r} declares both writable_custom_keys and "
                    "writable_custom_key_pattern; a container uses one or the other (D69)"
                )
        return self
