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

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from xtalate.capabilities import CapabilityMatrix
from xtalate.conversion.report import PreservedEntry, RemovedEntry, ReportWarning
from xtalate.recovery import RecoveryError, UnresolvedScenario, available_options
from xtalate.schema import CanonicalObject, PresenceMap
from xtalate.schema.paths import DERIVED_PATHS as _DERIVED_PATHS
from xtalate.schema.paths import OCCUPANCY_CUSTOM_KEY, is_full_occupancy
from xtalate.sdk import CapabilityLevel, FormatCapabilities

# `_DERIVED_PATHS` (`atoms.atomic_numbers`) is a derived mirror of `atoms.symbols` (Part 2 §3.3),
# not independent source information, so it is excluded from the diff and the completeness invariant
# — a format that writes symbols reconstitutes it. Defined once in `schema.paths` (a schema fact).
# Provenance is already excluded upstream (presence §3.11).

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

# The container holding fractional site occupancy, the Canonical Model's one *named* gap
# (Part 3 §3 n.11). Occupancy needs its own warning on top of the ordinary `removed` entry for
# this container: dropping an occupancy column does not merely lose an annotation, it changes what
# the output *asserts* — a site written with no occupancy reads as fully occupied, a claim the
# source never made. `removed` says "we did not carry this"; the warning says "and the file you get
# describes a different structure". A target that *represents* occupancy — naming the key in its
# `writable_custom_keys` — suppresses it with no change here (**P6**).
_OCCUPANCY_CONTAINER = "user_metadata.custom_per_atom"

# Opt-in fabricative scenarios: a canonical field the target *can* write but does not *require*, so
# the pre-flight diff never demands it. Emission is requested by the user supplying a recovery
# choice for the scenario (Part 4 §3.3, "user requests velocity emission for a target that supports
# them") — see `on_demand_fabricative_scenarios`.
_OPT_IN_FABRICATIVE = {
    "missing_velocities": "dynamics.velocities",
    "missing_masses": "atoms.masses",
}


@dataclass
class PreflightDiff:
    preserved: list[PreservedEntry] = field(default_factory=list)
    removed: list[RemovedEntry] = field(default_factory=list)
    warnings: list[ReportWarning] = field(default_factory=list)
    # Canonical paths the exporter is cleared to write (the write_plan, Part 4 §1). Usually
    # container-level; a custom_* container a format writes only *specific* keys of contributes
    # per-key entries (`user_metadata.custom_per_frame['xyz:comment']`) instead, so `canonical′`
    # keeps exactly those keys. `_apply_write_plan` accepts either granularity.
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


def partial_occupancy_count(custom_per_atom: Mapping[str, Any]) -> int:
    """How many atoms carry an occupancy that is not full, from a ``custom_per_atom`` mapping.

    A scalar, deliberately: it is derived identically from a materialized object's
    ``user_metadata.custom_per_atom`` and from a ``StreamHeader``'s, which is what keeps the
    streamed and materialized diffs identical (standing rule 3). Zero when the source declares no
    occupancy at all — absence of the column is not a claim of partial occupancy (**P3**).

    An *unknown* occupancy (``?``/``.``, carried through as ``None``) counts as partial. It is not
    a statement of full occupancy, and writing it out as a plain site would turn the source's
    silence into an assertion (**P4**).
    """
    values = custom_per_atom.get(OCCUPANCY_CUSTOM_KEY)
    if values is None:
        return 0
    return sum(1 for value in values if not is_full_occupancy(value))


def build_preflight(
    source: CanonicalObject, matrix: CapabilityMatrix, target_format_id: str
) -> PreflightDiff:
    """Compute the pre-flight diff of ``source`` against the target's write capabilities."""
    return build_preflight_from_presence(
        source.field_presence(),
        frame_count=source.frame_count,
        has_constraints=_has_constraints(source),
        partial_occupancy=partial_occupancy_count(source.user_metadata.custom_per_atom),
        matrix=matrix,
        target_format_id=target_format_id,
    )


def build_preflight_from_presence(
    presence: PresenceMap,
    *,
    frame_count: int,
    has_constraints: bool,
    partial_occupancy: int,
    matrix: CapabilityMatrix,
    target_format_id: str,
) -> PreflightDiff:
    """The presence-driven core of the pre-flight diff (M12).

    ``build_preflight`` reads exactly four things from the source object — its ``field_presence``,
    its ``frame_count``, whether any frame carries constraints, and how many atoms carry partial
    occupancy — and this function is that logic expressed over those four inputs directly. The
    streaming Conversion path derives all four single-pass (``schema.PresenceAccumulator`` +
    frame/constraint counters + the header's ``custom_per_atom``) and calls here, so a streamed
    conversion and a materialized one produce the *identical* diff — and therefore the identical
    Conversion Report (standing rule 3: streamed and materialized reports never diverge).

    They stay *scalars* on purpose. Handing this function the object would let the two paths drift
    the moment one of them had something the other did not.
    """
    caps = matrix.get(target_format_id, "write")
    diff = PreflightDiff()

    # A non-empty source constraint list against a PARTIAL target routes to the
    # `constraint_representation` scenario instead of auto-Preserve (M7). An empty `constraints=[]`
    # ("explicitly unconstrained", Part 2 §3.6) carries no subset to choose and preserves normally.
    constraints_need_recovery = has_constraints and (
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

        # A custom_* container the target writes only *specific* keys of (Part 3 §4.2): classify
        # per-key, not by the container level. A declared key is Preserved and enters the write plan
        # *per key* (so only it survives into `canonical′`); any other present key is Removed — the
        # exporter cannot express it, and predicting it Preserved would false-fail validation when
        # the exporter drops it. Plain XYZ, e.g., holds only its `xyz:comment` free-text line.
        # The same classification for a container whose writable set is a *name pattern* rather than
        # a fixed list (D69) — extXYZ writes arbitrary per-atom columns, but only under names its
        # `Properties=` grammar can spell and its parser reads back unchanged. Routed here, before
        # any bytes exist, because an unwritable name does not merely get dropped by the extXYZ
        # exporter: it corrupts the header and the output file will not parse at all.
        allowed = caps.writable_custom_keys.get(container)
        pattern = caps.writable_custom_key_pattern.get(container)
        if (allowed is not None or pattern is not None) and path != container:
            key = _custom_key(path)
            is_writable = (
                key in allowed
                if allowed is not None
                else re.fullmatch(pattern or "", key) is not None
            )
            if is_writable:
                diff.preserved.append(PreservedEntry(path=path, detail=detail))
                diff.write_plan.add(path)
            else:
                default = (
                    f"Target format {target_format_id!r} stores only {allowed} in {container}."
                    if allowed is not None
                    else (
                        f"Target format {target_format_id!r} can only store keys matching "
                        f"{pattern!r} in {container}."
                    )
                )
                diff.removed.append(
                    RemovedEntry(path=path, reason=cap.notes or default, detail=detail)
                )
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

    # Partial occupancy the target cannot hold (Part 3 §3 n.11). Gated on the target's declared
    # write keys, not on a hard-coded format list, so a future format that can express occupancy
    # silences this by declaring the key (**P6**).
    if partial_occupancy:
        # The gate is a target *naming* the occupancy key in `writable_custom_keys`, not merely
        # declaring the container writable. A format with a generic per-atom passthrough (extXYZ,
        # ASE .traj) carries the numbers, but as an unlabelled extra column no reader interprets as
        # occupancy — the structure it describes is still fully occupied at every site. Verbatim
        # carriage is not representation, and only the explicit declaration says otherwise.
        writable = caps.writable_custom_keys.get(_OCCUPANCY_CONTAINER)
        represents_occupancy = writable is not None and OCCUPANCY_CUSTOM_KEY in writable
        if not represents_occupancy:
            diff.warnings.append(
                ReportWarning(
                    code="PARTIAL_OCCUPANCY_NOT_REPRESENTED",
                    message=(
                        f"{partial_occupancy} atom(s) carry a site occupancy that is not 1.0, and "
                        f"target format {target_format_id!r} has no way to express it. The output "
                        "describes a structure that is fully occupied at every site, which is not "
                        "what the source said. Where the target can hold a custom per-atom column "
                        "the values are carried verbatim, but nothing downstream reads them as "
                        "occupancy. Occupancy is a known gap in the Canonical Model "
                        "(Part 3 §3 n.11), not an oversight of this target."
                    ),
                    source="capability",
                )
            )

    # lossy_notes → Warnings (Part 3 §4.3 rule 5).
    for note in caps.lossy_notes:
        diff.warnings.append(
            ReportWarning(code="FORMAT_LOSSY_NOTE", message=note, source="capability")
        )

    # Recovery triggers (Part 3 §4.3 rules 3–4, Part 4 §3.3). Detection order does not fix
    # resolution order — the Recovery Engine resolves in its own dependency order (frame_selection
    # before the bounding box computed on the selected frame).
    if caps.max_frames is not None and frame_count > caps.max_frames:
        diff.unresolved.append(
            UnresolvedScenario(
                scenario="frame_selection",
                detail=f"{frame_count} frames → target holds at most {caps.max_frames}",
                options=_scenario_options("frame_selection", caps),
            )
        )
    for required in caps.required_fields:
        # A required per-frame field that is *not uniformly present* (``absent`` everywhere, or
        # ``mixed`` — present in some frames only) may be missing from the frame that survives a
        # ``frame_selection`` reduction, so the recovery scenario is offered here and resolved
        # lazily against the post-reduction object (``recovery.engine``): it fabricates only when
        # the retained frame actually lacks the field, and no-ops when it carries a real value.
        # Offering it only on a fully-``absent`` field left a ``mixed`` cell to reach a lattice-
        # requiring exporter with no cell and crash (Part 4 §3.3; the M10 stage-2 test found it).
        if presence.status_of(required) != "present":
            scenario = _REQUIRED_FIELD_SCENARIOS.get(required, "missing_required_field")
            status = presence.status_of(required)
            diff.unresolved.append(
                UnresolvedScenario(
                    scenario=scenario,
                    path=required,
                    detail=f"target requires {required}, {status} on source",
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


def on_demand_fabricative_scenarios(
    source: CanonicalObject,
    matrix: CapabilityMatrix,
    target_format_id: str,
    recovery_choices: dict[str, dict[str, Any]],
    *,
    mode: str,
) -> list[UnresolvedScenario]:
    """The opt-in fabricative scenarios a *user-supplied* recovery choice pulls in (Part 4 §3.3).

    Unlike ``build_preflight``'s triggers (a target-*required* field absent, or too many frames),
    velocity/mass emission is **opt-in**: the target *can* write the field but does not require it,
    so nothing is fabricated unless the user asks by supplying a recovery choice. This is kept
    deliberately out of ``build_preflight`` (which must stay pure and choice-independent so the
    pre-flight *draft* means the same thing before any choice is made, D46);
    ``ConversionEngine.convert`` is the sole caller, merging these with ``diff.unresolved`` first.

    For each opt-in scenario the user asked for — plus ``missing_masses`` pulled in by a chained
    ``maxwell_boltzmann`` velocity choice when masses are absent — this emits an
    ``UnresolvedScenario``, or raises ``RecoveryError`` (a caller error, not a refusal) when the
    request is incoherent: the
    field is already present on the source (fabrication would overwrite real data, **P4**), or the
    user asked to *emit* a field the target cannot store. A chained ``missing_masses`` for a target
    that cannot store masses (POSCAR) is legal — ``params['emit']=False`` marks it as feeding the
    velocity draw only, recorded in ``supplied`` but never written (D47)."""
    presence = source.field_presence()
    scenarios: list[UnresolvedScenario] = []
    for scenario, path in _OPT_IN_FABRICATIVE.items():
        requested = scenario in recovery_choices
        chained = (
            scenario == "missing_masses"
            and recovery_choices.get("missing_velocities", {}).get("choice") == "maxwell_boltzmann"
            and presence.status_of("atoms.masses") == "absent"
        )
        if not (requested or chained):
            continue
        if presence.status_of(path) != "absent":
            raise RecoveryError(
                f"{scenario!r}: {path!r} is already present on the source; fabricating it would "
                "overwrite real data (P4) — remove the recovery choice"
            )
        emit = (
            matrix.field_capability(target_format_id, "write", path).level != CapabilityLevel.NONE
        )
        if requested and not chained and not emit:
            raise RecoveryError(
                f"{scenario!r}: target {target_format_id!r} cannot write {path!r}, so it cannot be "
                "emitted — drop the recovery choice or choose a target that supports it"
            )
        detail = (
            f"user requested emission of {path}, absent on source"
            if emit
            else f"{path} fabricated to seed a velocity draw only (target cannot store it)"
        )
        scenarios.append(
            UnresolvedScenario(
                scenario=scenario,
                path=path,
                detail=detail,
                options=available_options(
                    scenario,
                    target_field_optional=True,
                    permissive_mode=(mode == "permissive"),
                ),
                params={"emit": emit},
            )
        )
    return scenarios


def _custom_key(path: str) -> str:
    """Extract the dynamic key from a custom-container presence path (Part 2 §3.11), e.g.
    ``user_metadata.custom_per_frame['xyz:comment']`` → ``xyz:comment``. Returns ``path`` unchanged
    if it carries no ``['…']`` suffix (not a per-key custom path)."""
    start = path.find("['")
    end = path.rfind("']")
    return path[start + 2 : end] if start != -1 and end != -1 and end > start else path


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
