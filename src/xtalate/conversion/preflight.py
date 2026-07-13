"""The pre-flight diff — presence × write-capability (MASTER_SPEC Part 3 §4.3).

The mechanical realization of **P5**: before any bytes are written, intersect what the
*source object contains* (`field_presence()`, Part 2 §3.11) with what the *target format can
write* (the Capability Matrix, Part 3 §4). Each source-present path is classified once:

* target capability ``FULL`` → **Preserved**;
* ``PARTIAL`` → **Preserved**, with the declared condition (`notes`) surfaced as the entry
  ``detail`` *and* a `capability`-source Warning — the condition is always shown, never
  silently assumed to hold (in v0.1 the condition is not evaluated per-object; DECISIONS.md D19);
* ``NONE`` → **Removed**, with the `notes`/generated reason.

Three triggers detect the need for the Recovery Engine (Part 4 §3): a target ``required_field``
absent on the source (``missing_lattice`` and its catalog siblings), ``frame_count > max_frames``
(``frame_selection``), and — new in M7 — **source constraints against a PARTIAL target**
(``constraint_representation``). A PARTIAL ``dynamics.constraints`` capability no longer
auto-Preserves: *which* constraints survive a partial translation changes the physics of any
downstream relaxation, so it becomes a recorded choice (Part 4 §3.3). NONE stays ordinary
bulk-reductive loss; FULL stays Preserved. The result is the raw material for the Conversion
Report, shared by the pre-flight draft and the final report so the two are structurally comparable
(§2).

Each emitted ``UnresolvedScenario`` carries its **honest, pair-specific option list** (Part 4
§3.3) — computed here, where the concrete target's capabilities are known — so the engine
validates choices against, and the refusal report shows, exactly one list.

This module is pure: it reads presence + capabilities and returns data. It never mutates the
object, calls an exporter, or resolves a recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xtalate.capabilities import CapabilityMatrix
from xtalate.conversion.report import PreservedEntry, RemovedEntry, ReportWarning
from xtalate.recovery import UnresolvedScenario, available_options
from xtalate.schema import CanonicalObject
from xtalate.sdk import CapabilityLevel, FormatCapabilities

# `atoms.atomic_numbers` is a derived mirror of `atoms.symbols` (Part 2 §3.3), not independent
# source information, so it is excluded from the diff and the completeness invariant — a format
# that writes symbols reconstitutes it. Provenance is already excluded upstream (presence §3.11).
_DERIVED_PATHS = frozenset({"atoms.atomic_numbers"})

# A target required-field that is absent on the source maps to the recovery scenario that can
# supply it (Part 4 §3.3). Only `cell.lattice_vectors` (→ `missing_lattice`) is *required* by a v0.1
# target (POSCAR); the rest are declared for extensibility — a future target that requires them
# would trigger the matching scenario with no core change (**P6**).
_REQUIRED_FIELD_SCENARIOS = {
    "cell.lattice_vectors": "missing_lattice",
    "atoms.symbols": "missing_species",
    "dynamics.velocities": "missing_velocities",
    "atoms.masses": "missing_masses",
    "electronic.total_energy": "missing_energy",
}

# The container-level capability key governing per-atom constraint representation (Part 4 §3.3).
_CONSTRAINTS = "dynamics.constraints"


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
    # Source-present paths whose fate a *scenario* decides (e.g. `dynamics.constraints` under
    # `constraint_representation`): kept out of `preserved`/`removed`/`write_plan` so the resolver
    # is their sole accounting on the success path, but listed as predicted-preserved in pre-flight
    # draft and the pre-recovery refusal (the optimistic pre-flight convention) so the completeness
    # invariant holds before a choice is made (Part 4 §2, §3.3).
    pending: list[PreservedEntry] = field(default_factory=list)


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

    # A non-empty source constraint list against a PARTIAL target routes to the
    # `constraint_representation` scenario instead of auto-Preserve (M7). An empty `constraints=[]`
    # ("explicitly unconstrained", Part 2 §3.6) carries no subset to choose and preserves normally.
    constraints_need_recovery = _has_constraints(source) and (
        matrix.field_capability(target_format_id, "write", _CONSTRAINTS).level
        == CapabilityLevel.PARTIAL
    )

    for entry in presence.entries:
        path = entry.path
        if entry.status not in ("present", "mixed") or path in _DERIVED_PATHS:
            continue
        container = capability_path(path)
        cap = matrix.field_capability(target_format_id, "write", container)
        detail = _frame_detail(entry.status, entry.present_frames)

        # Source constraints against a PARTIAL target are not auto-Preserved (M7, Part 4 §3.3): the
        # `constraint_representation` scenario (emitted once, below) records which subset survives.
        # The kept subset's `preserved` entry and the dropped remainder's `removed` entry are
        # produced by the resolver, not here. The path is parked in `pending` so the pre-flight
        # draft and the pre-recovery refusal can still account for it (the optimistic-preserve
        # convention) and satisfy the completeness invariant before a choice is made.
        if container == _CONSTRAINTS and constraints_need_recovery:
            diff.pending.append(PreservedEntry(path=path, detail=detail))
            continue

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

    # Recovery triggers (Part 3 §4.3 rules 3–4, Part 4 §3.3). Detection order does not fix
    # resolution order — the Recovery Engine resolves in its own dependency order (frame_selection
    # before the bounding box computed on the selected frame).
    if caps.max_frames is not None and source.frame_count > caps.max_frames:
        diff.unresolved.append(
            UnresolvedScenario(
                scenario="frame_selection",
                detail=f"{source.frame_count} frames → target holds at most {caps.max_frames}",
                options=_scenario_options("frame_selection", caps),
            )
        )
    for required in caps.required_fields:
        if presence.status_of(required) == "absent":
            scenario = _REQUIRED_FIELD_SCENARIOS.get(required, "missing_required_field")
            diff.unresolved.append(
                UnresolvedScenario(
                    scenario=scenario,
                    path=required,
                    detail=f"target requires {required}, absent on source",
                    options=_scenario_options(scenario, caps),
                )
            )
    # constraint_representation: source has constraints, target can hold only a subset (PARTIAL).
    if constraints_need_recovery:
        diff.unresolved.append(
            UnresolvedScenario(
                scenario="constraint_representation",
                path=_CONSTRAINTS,
                detail=(
                    f"target represents only {caps.representable_constraint_kinds} "
                    "constraint kinds; a partial translation is a recorded choice"
                ),
                options=_scenario_options("constraint_representation", caps),
                params={"representable_kinds": list(caps.representable_constraint_kinds)},
            )
        )
    return diff


def _scenario_options(scenario: str, caps: FormatCapabilities) -> list[str]:
    """The honest, pair-specific option list for ``scenario`` given the target's capabilities
    (Part 4 §3.3). ``non_periodic`` only when the target can express an open cell; ``split_all``
    only when multi-file output is supported — which the Slice-2 ``ConversionResult.outputs`` path
    now provides for every single-structure target, so it is always available where
    ``frame_selection`` triggers (only single-structure targets, whose ``max_frames`` a trajectory
    exceeds)."""
    return available_options(
        scenario,
        target_can_be_nonperiodic=caps.allows_open_boundaries,
        target_supports_multifile=True,
    )


def _has_constraints(source: CanonicalObject) -> bool:
    """True iff any frame carries a non-empty ``dynamics.constraints`` list (Part 2 §3.6)."""
    return any(
        frame.dynamics.constraints is not None and len(frame.dynamics.constraints) > 0
        for frame in source.frames
    )


def _frame_detail(status: str, present_frames: list[int] | None) -> str | None:
    if status == "mixed" and present_frames is not None:
        return f"present in frames {present_frames}"
    return None
