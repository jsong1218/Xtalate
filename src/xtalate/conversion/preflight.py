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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from xtalate.capabilities import CapabilityMatrix
from xtalate.conversion.report import PreservedEntry, RemovedEntry, ReportWarning
from xtalate.recovery import RecoveryError, UnresolvedScenario, available_options
from xtalate.schema import CanonicalObject, PresenceMap
from xtalate.schema.paths import DERIVED_PATHS as _DERIVED_PATHS
from xtalate.schema.paths import is_full_occupancy
from xtalate.sdk import STRESS_CARRY_KEYS, CapabilityLevel, FormatCapabilities

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

#: The generic scenario emitted for a target ``required_field`` with no catalog-specific mapping
#: (**P6** — exactly the code a plugin format's unusual required field surfaces). Public so the
#: vocabulary export (`backend.vocabulary`) can enrol it in the UI mapping lint: without that, the
#: one code designed for *unforeseen* fields is the one code the lint cannot see.
GENERIC_REQUIRED_FIELD_SCENARIO = "missing_required_field"

# The container-level capability key governing per-atom constraint representation (Part 4 §3.3).
_CONSTRAINTS = "dynamics.constraints"

# The first-class per-atom occupancy field (M35). Partial occupancy needs its own warning on top
# of the ordinary `removed` entry the main loop already emits for this path against a target that
# cannot store it: dropping occupancy does not merely lose an annotation, it changes what the
# output *asserts* — a site written with no occupancy reads as fully occupied, a claim the source
# never made. `removed` says "we did not carry this"; the warning says "and the file you get
# describes a different structure". A target that *represents* occupancy — declaring a writable
# `atoms.occupancies` capability — suppresses the warning with no change here (**P6**).
_OCCUPANCY_PATH = "atoms.occupancies"

# The stress-carry keys (M40; generalized to the shared set in M42-S5, D163): the per-frame
# custom keys owned by the ASE-backed parsers (``extxyz:stress``, ``ase_traj:stress``, DECISIONS.md
# D18) plus their presence-path forms. The set is named in exactly one place —
# ``xtalate.sdk.stress_carries`` — so a future format adds its carry key there and both this
# detection and the recovery resolver see it (neither layer imports parsers). A source that
# carries one of these and a target that can express ``electronic.stress`` is the
# ``ambiguous_stress_convention`` detection shape — a present-but-unmapped carry, neither the
# fabricative "required field absent" shape nor the reductive "present field the target cannot
# hold" shape (Part 4 §3.3, M40).
_STRESS_CARRY_KEYS = tuple(STRESS_CARRY_KEYS)
_STRESS_CARRY_PATHS = {
    key: f"user_metadata.custom_per_frame['{key}']" for key in _STRESS_CARRY_KEYS
}
_ELECTRONIC_STRESS = "electronic.stress"

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


def partial_occupancy_count(occupancies: Sequence[float | None] | None) -> int:
    """How many atoms carry an occupancy that is not full, from an ``atoms.occupancies`` list.

    A scalar, deliberately: the materialized path derives it from ``frames[0].atoms.occupancies``
    and the streamed path never carries occupancy at all (only CIF, a single-structure format,
    populates it), which is what keeps the streamed and materialized diffs identical (standing
    rule 3). ``None`` — the source declared no occupancy — is zero: absence of the column is not a
    claim of partial occupancy (**P3**).

    An *unknown* occupancy (``?``/``.``, held per site as ``None``) counts as partial. It is not a
    statement of full occupancy, and writing it out as a plain site would turn the source's silence
    into an assertion (**P4**).
    """
    if occupancies is None:
        return 0
    return sum(1 for value in occupancies if not is_full_occupancy(value))


def build_preflight(
    source: CanonicalObject,
    matrix: CapabilityMatrix,
    target_format_id: str,
    *,
    output_multifile: bool = True,
) -> PreflightDiff:
    """Compute the pre-flight diff of ``source`` against the target's write capabilities.

    ``output_multifile`` declares whether the caller's output sink accepts multiple files, gating
    the ``split_all`` recovery option (Part 4 §3.3): ``True`` for the CLI (writes a directory),
    ``False`` for the single-download HTTP service. Defaults ``True`` so the library/CLI behaviour
    is unchanged."""
    return build_preflight_from_presence(
        source.field_presence(),
        frame_count=source.frame_count,
        has_constraints=_has_constraints(source),
        partial_occupancy=partial_occupancy_count(source.frames[0].atoms.occupancies),
        matrix=matrix,
        target_format_id=target_format_id,
        output_multifile=output_multifile,
    )


def build_preflight_from_presence(
    presence: PresenceMap,
    *,
    frame_count: int,
    has_constraints: bool,
    partial_occupancy: int,
    matrix: CapabilityMatrix,
    target_format_id: str,
    output_multifile: bool = True,
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

    # The `ambiguous_stress_convention` trigger (M40; generalized to the shared key set in
    # M42-S5, D163): a present-but-unmapped carry. Stress is a source field that is *present*
    # (parked in a custom carry) which the target *could* express as the canonical
    # `electronic.stress` — neither of the two existing detection shapes. It fires when both
    # hold: any registered stress-carry key is present on the source **and** the target
    # declares a non-NONE write capability for `electronic.stress` (checked against the
    # capability declaration, so the branch is correct the moment a format's exporter flips its
    # row — M40-S2, M42-S5 — with no change here). Each present key emits its own scenario with
    # the key on `params`, so the resolver knows which array to read and which to retire.
    present_stress_keys = [
        key
        for key in _STRESS_CARRY_KEYS
        if presence.status_of(_STRESS_CARRY_PATHS[key]) != "absent"
    ]
    stress_need_recovery = bool(present_stress_keys) and (
        matrix.field_capability(target_format_id, "write", _ELECTRONIC_STRESS).level
        != CapabilityLevel.NONE
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

        # The stress carry's fate is decided by the `ambiguous_stress_convention` scenario
        # (retired into `electronic.stress` on resolution, left as-is on refusal), so it is parked
        # in `pending` — the optimistic-preserve convention, exactly like `dynamics.constraints`
        # above — rather than classified against the container (which would predict it preserved
        # when the resolver then retires it, a report lie; or removed when the target's
        # custom-container capability is NONE, denying that the value survives interpretation).
        if path in _STRESS_CARRY_PATHS.values() and stress_need_recovery:
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

    # Partial occupancy the target cannot hold. Gated on the target's declared capability for the
    # first-class `atoms.occupancies` field, not a hard-coded format list, so a future format that
    # can express occupancy silences this by declaring that field writable (**P6**).
    if partial_occupancy:
        # The gate is the target declaring a writable `atoms.occupancies` capability. A format with
        # a generic per-atom passthrough (extXYZ, ASE .traj) might carry the numbers as an
        # unlabelled extra column, but no reader interprets that as occupancy — the structure it
        # describes is still fully occupied at every site. Verbatim carriage is not representation;
        # only the field capability says otherwise. (Non-CIF targets do not declare the field, so
        # it defaults to NONE and this fires.)
        occupancy_cap = caps.fields.get(_OCCUPANCY_PATH)
        represents_occupancy = occupancy_cap is not None and occupancy_cap.level in (
            CapabilityLevel.FULL,
            CapabilityLevel.PARTIAL,
        )
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
                options=_scenario_options(
                    "frame_selection", caps, output_multifile=output_multifile
                ),
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
            scenario = _REQUIRED_FIELD_SCENARIOS.get(required, GENERIC_REQUIRED_FIELD_SCENARIO)
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
    # ambiguous_stress_convention: a carried stress channel against a target that can express
    # `electronic.stress` — one scenario per present carry key, each naming its key so the
    # resolver reads the right array and retires the right one. The option list is computed here
    # (at detection time, when the pair is known) and carried on the scenario, so the engine
    # validates against — and the refusal report echoes — exactly one list (P5). `params` also
    # carries the custom-array location a future `virial` option would consult.
    if stress_need_recovery:
        for key in present_stress_keys:
            diff.unresolved.append(
                UnresolvedScenario(
                    scenario="ambiguous_stress_convention",
                    path=_ELECTRONIC_STRESS,
                    detail=(
                        f"source carries {STRESS_CARRY_KEYS[key]} stress verbatim in "
                        f"user_metadata.custom_per_frame[{key!r}]; the target can "
                        "express electronic.stress, so the stress sign convention must be "
                        "declared before it is promoted"
                    ),
                    options=available_options("ambiguous_stress_convention"),
                    params={"custom_key": key},
                )
            )
    return diff


def _scenario_options(
    scenario: str, caps: FormatCapabilities, *, output_multifile: bool = True
) -> list[str]:
    """The honest, pair-specific option list for ``scenario`` given the target's capabilities
    (Part 4 §3.3). ``non_periodic`` only when the target can express an open cell; ``split_all``
    only when the *caller's output sink* accepts multiple files.

    The engine's Slice-2 ``ConversionResult.outputs`` path can produce one file per frame for every
    single-structure target, so the *format* never blocks ``split_all`` — but the sink can. The
    catalog's own rule is that ``split_all`` is "offered when the job's output mode permits multiple
    files" (Part 4 §3.3): the CLI writes a directory and passes ``output_multifile=True`` (the
    default), while the HTTP service serves a single download and passes ``False`` — so the wizard
    never offers a choice the service cannot deliver, and a directly-posted ``split_all`` fails the
    Recovery Engine's offered-set check (a refusal, never a silently dropped output)."""
    return available_options(
        scenario,
        target_can_be_nonperiodic=caps.allows_open_boundaries,
        target_supports_multifile=output_multifile,
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
