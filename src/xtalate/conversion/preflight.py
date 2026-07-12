"""The pre-flight diff — presence × write-capability (MASTER_SPEC Part 3 §4.3).

The mechanical realization of **P5**: before any bytes are written, intersect what the
*source object contains* (`field_presence()`, Part 2 §3.11) with what the *target format can
write* (the Capability Matrix, Part 3 §4). Each source-present path is classified once:

* target capability ``FULL`` → **Preserved**;
* ``PARTIAL`` → **Preserved**, with the declared condition (`notes`) surfaced as the entry
  ``detail`` *and* a `capability`-source Warning — the condition is always shown, never
  silently assumed to hold (in v0.1 the condition is not evaluated per-object; DECISIONS.md D19);
* ``NONE`` → **Removed**, with the `notes`/generated reason.

Two further triggers detect the need for the Recovery Engine (Part 4 §3), which M4 only
*detects* (resolution is M5): a target ``required_field`` absent on the source, and
``frame_count > max_frames``. The result is the raw material for the Conversion Report, shared
by the pre-flight draft and the final report so the two are structurally comparable (§2).

This module is pure: it reads presence + capabilities and returns data. It never mutates the
object, calls an exporter, or resolves a recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xtalate.capabilities import CapabilityMatrix
from xtalate.conversion.report import PreservedEntry, RemovedEntry, ReportWarning
from xtalate.recovery import UnresolvedScenario
from xtalate.schema import CanonicalObject
from xtalate.sdk import CapabilityLevel

# `atoms.atomic_numbers` is a derived mirror of `atoms.symbols` (Part 2 §3.3), not independent
# source information, so it is excluded from the diff and the completeness invariant — a format
# that writes symbols reconstitutes it. Provenance is already excluded upstream (presence §3.11).
_DERIVED_PATHS = frozenset({"atoms.atomic_numbers"})

# A target required-field that is absent on the source maps to the recovery scenario that can
# supply it (Part 4 §3.3). Only the fabricative one exists in v0.1 (review §4.4 trim).
_REQUIRED_FIELD_SCENARIOS = {"cell.lattice_vectors": "missing_lattice"}


@dataclass
class PreflightDiff:
    preserved: list[PreservedEntry] = field(default_factory=list)
    removed: list[RemovedEntry] = field(default_factory=list)
    warnings: list[ReportWarning] = field(default_factory=list)
    # Container-level canonical paths the exporter is cleared to write (the write_plan, Part 4
    # §1). Custom_* containers are all-or-nothing at this granularity; per-key entries are still
    # reported individually in `preserved`/`removed`.
    write_plan: set[str] = field(default_factory=set)
    unresolved: list[UnresolvedScenario] = field(default_factory=list)


def capability_path(presence_path: str) -> str:
    """Map a presence path to the capability key it is governed by.

    Dynamic custom keys arrive as ``user_metadata.custom_per_frame['xyz:comment']`` (per §3.11)
    but capabilities are declared at the container level ``user_metadata.custom_per_frame``
    (Part 3 §4.1) — so the ``['key']`` suffix is stripped for the capability lookup while the
    per-key path is kept for the report entry.
    """
    bracket = presence_path.find("[")
    return presence_path[:bracket] if bracket != -1 else presence_path


def build_preflight(
    source: CanonicalObject, matrix: CapabilityMatrix, target_format_id: str
) -> PreflightDiff:
    """Compute the pre-flight diff of ``source`` against the target's write capabilities."""
    caps = matrix.get(target_format_id, "write")
    presence = source.field_presence()
    diff = PreflightDiff()

    for entry in presence.entries:
        path = entry.path
        if entry.status not in ("present", "mixed") or path in _DERIVED_PATHS:
            continue
        container = capability_path(path)
        cap = matrix.field_capability(target_format_id, "write", container)
        detail = _frame_detail(entry.status, entry.present_frames)

        if cap.level == CapabilityLevel.FULL:
            diff.preserved.append(PreservedEntry(path=path, detail=detail))
            diff.write_plan.add(container)
        elif cap.level == CapabilityLevel.PARTIAL:
            diff.preserved.append(PreservedEntry(path=path, detail=cap.notes or detail))
            diff.write_plan.add(container)
            if cap.notes:
                diff.warnings.append(
                    ReportWarning(code="PARTIAL_CAPABILITY", message=cap.notes, source="capability")
                )
        else:  # NONE
            reason = cap.notes or f"Target format {target_format_id!r} cannot store {container}."
            diff.removed.append(RemovedEntry(path=path, reason=reason, detail=detail))

    # lossy_notes → Warnings (Part 3 §4.3 rule 5).
    for note in caps.lossy_notes:
        diff.warnings.append(
            ReportWarning(code="FORMAT_LOSSY_NOTE", message=note, source="capability")
        )

    # Recovery triggers (Part 3 §4.3 rules 3–4) — detected here, resolved in M5.
    # Frame selection is ordered before missing_lattice (a bounding box is computed on the
    # selected frame — the dependency of Part 4 §3.3).
    if caps.max_frames is not None and source.frame_count > caps.max_frames:
        diff.unresolved.append(
            UnresolvedScenario(
                scenario="frame_selection",
                detail=f"{source.frame_count} frames → target holds at most {caps.max_frames}",
            )
        )
    for required in caps.required_fields:
        if presence.status_of(required) == "absent":
            diff.unresolved.append(
                UnresolvedScenario(
                    scenario=_REQUIRED_FIELD_SCENARIOS.get(required, "missing_required_field"),
                    path=required,
                    detail=f"target requires {required}, absent on source",
                )
            )
    return diff


def _frame_detail(status: str, present_frames: list[int] | None) -> str | None:
    if status == "mixed" and present_frames is not None:
        return f"present in frames {present_frames}"
    return None
