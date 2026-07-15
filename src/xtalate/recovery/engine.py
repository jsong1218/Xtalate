"""The Recovery Engine — explicit, never-guessed resolution of conversion hazards (Part 4 §3).

Given the scenarios the pre-flight diff could not resolve and a set of caller-supplied choices
(v0.1 is **preset-only**, DECISIONS.md D22), the engine either resolves *every* scenario — each
producing exactly one recorded ``Assumption`` — or resolves **none** and reports the refusal
(Part 4 §3.2: "refusal is the default"; there is no timeout-triggered or per-scenario silent
fallback). It never applies a choice the caller did not name (**P4**).

Layering (Part 1 §5.1). This module sits *below* ``conversion`` in the import graph, so it may
not import the Conversion Report schema (``conversion.report``). It returns its own plain result
types (``AppliedAssumption``, ``SuppliedField``, ``FrameDrop``); the ``ConversionEngine`` (top
layer) maps them onto ``Assumption``/``SuppliedEntry``/``RemovedEntry`` for the report. It depends
only on ``schema``.

**Dependency ordering (Part 4 §3.3).** Scenarios resolve in a fixed dependency order, not the order
they were detected: ``frame_selection`` first (a ``bounding_box`` lattice is computed on the
*selected* frame's positions), then ``constraint_representation`` (frame-independent), then
``missing_lattice``. Assumptions are numbered ``A1, A2, …`` in application order, matching the
worked example (A1 = frame_selection, A2 = missing_lattice; Part 4 §5).

**Generalized dispatch.** New scenarios attach at the ``_RESOLVERS`` table (**P6**) — a scenario is
resolvable iff it is classified in ``SCENARIO_HAZARD`` *and* has a resolver here; anything else
refuses. Each resolver receives the detected ``UnresolvedScenario`` so it can validate the choice
against that instance's honest ``options`` (computed for the concrete pair, Part 4 §3.3) and read
any detection ``params`` (e.g. the target's representable constraint kinds).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import ase.data
import numpy as np
from ase import units as ase_units

from xtalate.recovery.scenarios import (
    SCENARIO_HAZARD,
    UnresolvedScenario,
    available_options,
)
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame
from xtalate.schema.elements import atomic_number

# Resolution order (Part 4 §3.3): frame_selection first (a bounding box is computed on the chosen
# frame), then constraint projection (frame-independent), then the fabricated lattice, then the
# velocity family. `missing_masses` resolves *before* `missing_velocities` so a chained
# `maxwell_boltzmann` reads the masses the mass resolver has already written into the object.
_DEP_ORDER = (
    "frame_selection",
    "constraint_representation",
    "missing_lattice",
    "missing_masses",
    "missing_velocities",
)


class RecoveryError(ValueError):
    """A preset named an option that is not offered for this pair, or omitted a required
    parameter. Distinct from a *refusal* (no choice supplied): a refusal is a legitimate
    conversion outcome (Part 4 §4); an invalid preset is a caller error."""


@dataclass
class SuppliedField:
    """One canonical field a fabricative recovery wrote into the object (Part 4 §2, `supplied`).

    ``in_write_plan`` is ``True`` for a field the target will actually write; ``False`` for one
    fabricated purely to *feed another recovery* that the target cannot itself store — the chained
    ``missing_masses`` masses that seed a Maxwell–Boltzmann velocity draw but are dropped when the
    target (POSCAR) has no mass field. Such a field is still recorded in ``supplied`` (the audit
    trail the user asked for), but is kept out of the write plan so validation does not expect it in
    the output (D47)."""

    path: str
    detail: str | None = None
    in_write_plan: bool = True


@dataclass
class PreservedField:
    """A source field a *selective-reductive* recovery keeps (Part 4 §2, `preserved`).

    Distinct from ``SuppliedField``: the value is genuine source data the choice *retained*, not
    fabricated — so it lands in ``preserved`` (and the write plan), never ``supplied``. Emitted by
    ``constraint_representation``'s ``project`` for the representable subset it keeps."""

    path: str
    detail: str | None = None


@dataclass
class FrameDrop:
    """A ``removed`` entry for a selective-reductive reduction — dropped frames (frame_selection) or
    unrepresentable constraints (constraint_representation) (Part 4 §5 removed[0])."""

    path: str
    reason: str
    detail: str


@dataclass
class AppliedAssumption:
    """One recorded recovery decision (Part 4 §2 `Assumption`), plus its field-level effects.

    ``supplied`` is non-empty only for fabricative scenarios; ``preserved`` and ``removed`` only for
    selective-reductive ones (a ``project`` may carry both — the kept subset and the dropped
    remainder of one partially-retained path). ``supplied`` and ``preserved`` never overlap — the
    bright line of Part 4 §3.1 (fabricated vs. genuine-but-retained)."""

    id: str
    scenario: str
    choice: str
    parameters: dict[str, Any]
    origin: str  # "preset" | "user". v0.1 is preset-only (D22).
    description: str
    supplied: list[SuppliedField] = field(default_factory=list)
    preserved: list[PreservedField] = field(default_factory=list)
    removed: list[FrameDrop] = field(default_factory=list)


@dataclass
class RecoveryResult:
    """Outcome of ``resolve``. ``canonical`` is ``None`` iff the conversion is refused, in which
    case ``unresolved`` lists the scenarios that lacked a choice (Part 4 §3.2)."""

    canonical: CanonicalObject | None
    assumptions: list[AppliedAssumption]
    unresolved: list[UnresolvedScenario]


class RecoveryEngine:
    def resolve(
        self,
        source: CanonicalObject,
        scenarios: list[UnresolvedScenario],
        recovery_choices: dict[str, dict[str, Any]],
        *,
        origin: str = "preset",
    ) -> RecoveryResult:
        """Resolve every scenario in ``scenarios`` using ``recovery_choices`` (keyed by scenario
        code, each ``{"choice": str, "parameters": {...}}``), or refuse if any lacks a choice.

        Resolution is all-or-nothing: a single missing choice refuses the whole conversion, so
        no partially-recovered object is ever produced (a half-recovered structure presented as
        complete would be the very silent failure this engine exists to prevent)."""
        # A scenario is unresolvable if v0.1 does not know how to resolve it, or the caller
        # supplied no choice for it. Both refuse (Part 4 §3.2).
        unresolved = [
            s
            for s in scenarios
            if s.scenario not in SCENARIO_HAZARD or s.scenario not in recovery_choices
        ]
        if unresolved:
            return RecoveryResult(canonical=None, assumptions=[], unresolved=unresolved)

        working = source
        assumptions: list[AppliedAssumption] = []
        selected_source_index = 0  # threaded from frame_selection into bounding_box's description.
        counter = 1
        for scenario_code in _DEP_ORDER:
            match = next((s for s in scenarios if s.scenario == scenario_code), None)
            if match is None:
                continue
            aid = f"A{counter}"
            counter += 1
            choice = recovery_choices[scenario_code]
            if scenario_code == "frame_selection":
                working, applied, selected_source_index = _apply_frame_selection(
                    working, aid, choice, origin, match
                )
            elif scenario_code == "constraint_representation":
                working, applied = _apply_constraint_representation(
                    working, aid, choice, origin, match
                )
            elif scenario_code == "missing_masses":
                working, applied = _apply_missing_masses(working, aid, choice, origin, match)
            elif scenario_code == "missing_velocities":
                working, applied = _apply_missing_velocities(working, aid, choice, origin, match)
            else:  # missing_lattice
                working, applied = _apply_missing_lattice(
                    working, aid, choice, origin, match, computed_on_frame=selected_source_index
                )
            assumptions.append(applied)

        return RecoveryResult(canonical=working, assumptions=assumptions, unresolved=[])


def _choice_code(choice: dict[str, Any], scenario: UnresolvedScenario) -> str:
    """Validate the caller's choice against the *honest* option list for this detected scenario
    instance (Part 4 §3.3). The instance carries the pair-specific ``options`` (computed by
    pre-flight); a directly-constructed scenario with no options falls back to the default list.
    A choice outside the offered set is a *caller error* (``RecoveryError``), not a refusal."""
    offered = scenario.options or available_options(scenario.scenario)
    code = choice.get("choice")
    if not isinstance(code, str) or code not in offered:
        raise RecoveryError(
            f"{scenario.scenario!r}: choice {code!r} is not an offered option {offered!r}"
        )
    return code


# Canonical categories that live on ``Frame`` (Part 2 §3.5): a path under one of these is per-frame
# data, so a frame reduction can eliminate it. Root categories (trajectory/simulation/user_metadata)
# are not lost by frame_selection and are accounted for by the capability diff instead.
_PER_FRAME_PREFIXES = ("frame.", "atoms.", "cell.", "dynamics.", "electronic.")


def _per_frame_paths_lost(before: CanonicalObject, after: CanonicalObject) -> list[str]:
    """Per-frame canonical paths present in ``before`` but absent in the reduced ``after`` object —
    the fields a frame reduction eliminates entirely (present only in dropped frames). Derived from
    the object's own presence map so it stays correct as the schema grows (**P6**); ``atoms``
    symbols/positions survive into the retained frame and never appear here."""
    after_presence = after.field_presence()
    return [
        path
        for path in before.field_presence().present_paths()
        if path.startswith(_PER_FRAME_PREFIXES) and after_presence.status_of(path) == "absent"
    ]


def _apply_frame_selection(
    canonical: CanonicalObject,
    aid: str,
    choice: dict[str, Any],
    origin: str,
    scenario: UnresolvedScenario,
) -> tuple[CanonicalObject, AppliedAssumption, int]:
    """Reduce a multi-frame object to the single chosen frame (selective reductive, Part 4 §3.1).

    Records an ``Assumption`` and a ``FrameDrop`` (the dropped frames as a `removed` entry) but
    **no** ``SuppliedField`` — the retained frame is genuine source data, not fabricated."""
    code = _choice_code(choice, scenario)
    params = choice.get("parameters", {}) or {}
    n = canonical.frame_count

    if code == "split_all":
        # Keep every frame; the ConversionEngine writes one single-structure file per frame
        # (Part 4 §3.3). No frame is dropped, so there is no `removed` entry — the split changes
        # the output from one file to a set, which is the recorded choice. The selected-frame index
        # threaded onward is 0 (a chained bounding box, an exotic combination, boxes on frame 0).
        assumption = AppliedAssumption(
            id=aid,
            scenario="frame_selection",
            choice="split_all",
            parameters={"frame_count": n},
            origin=origin,
            description=(
                f"All {n} frames retained; the single-structure target receives one file per "
                "frame. No frame is dropped — the split is a recorded choice because it turns one "
                "output into a set of files, an outcome the caller must ask for explicitly."
            ),
        )
        return canonical, assumption, 0

    if code == "first":
        index = 0
    elif code == "last":
        index = n - 1
    else:  # "index"
        raw = params.get("frame_index")
        if not isinstance(raw, int) or isinstance(raw, bool) or not (0 <= raw < n):
            raise RecoveryError(
                f"frame_selection 'index' needs an in-range integer frame_index (0..{n - 1}), "
                f"got {raw!r}"
            )
        index = raw

    selected = canonical.frames[index]
    reduced_frame = selected.model_copy(update={"index": 0})
    # custom_per_frame arrays carry first-dim = frame count (Part 2 §3.10); slice to the kept frame.
    um = canonical.user_metadata
    sliced_per_frame: dict[str, Any] = {}
    for key, val in um.custom_per_frame.items():
        sliced_per_frame[key] = (
            val[index : index + 1] if isinstance(val, np.ndarray) else [val[index]]
        )
    new_um = um.model_copy(update={"custom_per_frame": sliced_per_frame})

    reduced = canonical.model_copy(
        update={"frames": [reduced_frame], "trajectory": None, "user_metadata": new_um}
    )
    dropped = n - 1
    removed = [
        FrameDrop(
            path="atoms.positions",
            reason="Target format stores a single structure (max_frames = 1).",
            detail=f"{dropped} of {n} frames dropped; frame {index} retained per {aid}.",
        )
    ]
    # A per-frame field that lived *only* in the dropped frames (a `mixed` path, present in the
    # source but absent from the retained frame — e.g. constraints on frame 3 of a 4-frame run) is
    # eliminated entirely by the reduction. The reduction is the operation that loses it, so it must
    # be recorded here, or it lands in neither `preserved` nor `removed` and the completeness
    # invariant fires (P1). Without this, a `constraint_representation` running *after* frame_
    # selection (dependency order) sees a constraint-free object and records nothing — silent loss.
    # Root losses (e.g. `trajectory.timestep`) are the capability diff's job, so this is per-frame.
    lost = _per_frame_paths_lost(canonical, reduced)
    for path in lost:
        removed.append(
            FrameDrop(
                path=path,
                reason="Present only in dropped frame(s); the retained frame carries no value.",
                detail=f"{path} appeared in the source but not in retained frame {index}.",
            )
        )
    assumption = AppliedAssumption(
        id=aid,
        scenario="frame_selection",
        choice=code,
        parameters={"frame_index": index},
        origin=origin,
        description=(
            f"Frame {index} of {n} selected for the single-structure target; the other "
            f"{dropped} frame(s) are dropped. Which frame survives changes the scientific "
            "meaning of the output, so this is a recorded choice, not a silent default."
        ),
        removed=removed,
    )
    return reduced, assumption, index


def _apply_constraint_representation(
    canonical: CanonicalObject,
    aid: str,
    choice: dict[str, Any],
    origin: str,
    scenario: UnresolvedScenario,
) -> tuple[CanonicalObject, AppliedAssumption]:
    """Resolve source constraints a target can only *partially* represent (selective reductive,
    Part 4 §3.1, §3.3).

    ``project`` keeps the constraints whose ``kind`` is in the target's representable set (recorded
    as ``preserved`` — genuine data retained, **not** fabricated) and drops the rest (``removed``).
    ``drop_all`` keeps none. Either way one ``Assumption`` is recorded and **no** ``SuppliedField``
    — the selective-reductive bright line. A partial constraint translation changes the physics of
    any downstream relaxation, which is exactly why the catalog makes it a recorded choice rather
    than a silent reduction (Part 4 §3.3)."""
    code = _choice_code(choice, scenario)
    representable = set(scenario.params.get("representable_kinds", []))

    new_frames = []
    kept_total = 0
    dropped_counts: dict[str, int] = {}
    for frame in canonical.frames:
        kept = []
        for constraint in frame.dynamics.constraints or []:
            if code == "project" and constraint.kind in representable:
                kept.append(constraint)
            else:  # unrepresentable (project), or every constraint (drop_all)
                dropped_counts[constraint.kind] = dropped_counts.get(constraint.kind, 0) + 1
        kept_total += len(kept)
        new_dynamics = frame.dynamics.model_copy(update={"constraints": kept or None})
        new_frames.append(frame.model_copy(update={"dynamics": new_dynamics}))

    updated = canonical.model_copy(update={"frames": new_frames})
    kinds = sorted(representable)
    total_dropped = sum(dropped_counts.values())

    preserved: list[PreservedField] = []
    if kept_total > 0:
        preserved.append(
            PreservedField(
                path="dynamics.constraints",
                detail=f"{kept_total} representable constraint(s) kept ({kinds}).",
            )
        )
    removed: list[FrameDrop] = []
    if total_dropped > 0:
        removed.append(
            FrameDrop(
                path="dynamics.constraints",
                reason=(
                    f"Target represents only {kinds} constraint kinds; "
                    "other constraints cannot be written."
                ),
                detail=(
                    f"{total_dropped} constraint(s) dropped across frames: "
                    f"{dict(sorted(dropped_counts.items()))}."
                ),
            )
        )
    # The path can be *present* yet contribute zero kept and zero dropped constraints: an
    # explicitly-unconstrained ``constraints=[]`` ("no constraints" is itself data, §3.6) in the
    # remaining frame(s), reached when frame_selection dropped the frame that held the real
    # constraints. The resolver still nulls it out of the write plan, so that present path becomes
    # absent — a removal that must be recorded, or the pending `dynamics.constraints` lands in
    # neither preserved nor removed and the completeness invariant fires (P1).
    input_present = any(frame.dynamics.constraints is not None for frame in canonical.frames)
    if input_present and kept_total == 0 and total_dropped == 0:
        removed.append(
            FrameDrop(
                path="dynamics.constraints",
                reason="Target does not record an explicitly-unconstrained (empty) constraint set.",
                detail="Source declared no constraints on the retained frame(s); not written.",
            )
        )

    if code == "project":
        parameters: dict[str, Any] = {
            "representable_kinds": kinds,
            "dropped_kinds": dict(sorted(dropped_counts.items())),
        }
        description = (
            f"Constraints projected onto the target's representable subset {kinds}: {kept_total} "
            f"kept, {total_dropped} dropped. A partial constraint translation changes the physics "
            "of a downstream relaxation, so it is a recorded choice, not a silent reduction."
        )
    else:  # drop_all
        parameters = {"dropped": total_dropped}
        description = (
            f"All {total_dropped} source constraint(s) dropped at the caller's explicit request "
            f"(the target could represent {kinds}, but drop_all keeps none). Recorded so a "
            "downstream relaxation is never silently unconstrained."
        )

    assumption = AppliedAssumption(
        id=aid,
        scenario="constraint_representation",
        choice=code,
        parameters=parameters,
        origin=origin,
        description=description,
        preserved=preserved,
        removed=removed,
    )
    return updated, assumption


def _apply_missing_lattice(
    canonical: CanonicalObject,
    aid: str,
    choice: dict[str, Any],
    origin: str,
    scenario: UnresolvedScenario,
    *,
    computed_on_frame: int,
) -> tuple[CanonicalObject, AppliedAssumption]:
    """Fabricate the target-required lattice the source lacks (fabricative, Part 4 §3.1).

    Writes ``cell.lattice_vectors`` and ``cell.pbc`` into every frame and records an
    ``Assumption`` **and** two ``SuppliedField`` entries — the cell did not exist in the source,
    so it is filed as created, never carried (**P4**). ``pbc`` is set to (T,T,T): POSCAR, the only
    v0.1 lattice-requiring target, is fully periodic by definition (Part 3 §3 n.3)."""
    code = _choice_code(choice, scenario)
    params = choice.get("parameters", {}) or {}
    pbc = (True, True, True)

    if code == "manual_input":
        raw = params.get("lattice")
        lattice = _as_lattice(raw)
        new_frames = [_frame_with_cell(f, lattice, pbc) for f in canonical.frames]
        report_params: dict[str, Any] = {"lattice_ang": lattice.tolist()}
        description = (
            "Lattice supplied manually by the caller; pbc set to (T,T,T) as required by the "
            "target. The source expressed no lattice — this cell is an artifact of conversion, "
            "not simulation data."
        )
    elif code == "upload_reference":
        lattice = _lattice_from_reference(params.get("reference"), canonical)
        new_frames = [_frame_with_cell(f, lattice, pbc) for f in canonical.frames]
        report_params = {
            "reference_atom_count": canonical.frames[0].atoms.positions.shape[0],
            "lattice_ang": lattice.tolist(),
        }
        description = (
            "Lattice taken from a second uploaded reference structure whose atom count matches the "
            "source; pbc set to (T,T,T) as required by the target. The source file expressed no "
            "lattice — this cell is borrowed from the reference, not present in the source."
        )
    else:  # "bounding_box"
        padding = params.get("padding_ang")
        if not isinstance(padding, (int, float)) or padding < 0:
            raise RecoveryError(
                f"missing_lattice 'bounding_box' needs a non-negative padding_ang, got {padding!r}"
            )
        padding = float(padding)
        # Box is computed on the (already-selected) single frame; if several frames remain the
        # same box is applied to each (no v0.1 pair reaches here multi-frame).
        positions = canonical.frames[0].atoms.positions
        lattice, shift = _bounding_box(positions, padding)
        new_frames = [_frame_with_cell(f, lattice, pbc, shift=shift) for f in canonical.frames]
        report_params = {"padding_ang": padding, "computed_on_frame": computed_on_frame}
        description = (
            f"Lattice constructed as the axis-aligned bounding box of frame {computed_on_frame}'s "
            f"positions plus {padding} Å padding on each side; atoms rigidly translated into that "
            "box (a shift preserves all interatomic distances). pbc set to (T,T,T) as required by "
            "the target. The source expressed no lattice — this cell is a conversion artifact, "
            "not simulation data."
        )

    updated = canonical.model_copy(update={"frames": new_frames})
    assumption = AppliedAssumption(
        id=aid,
        scenario="missing_lattice",
        choice=code,
        parameters=report_params,
        origin=origin,
        description=description,
        supplied=[
            SuppliedField(
                path="cell.lattice_vectors",
                detail="3×3 lattice fabricated by recovery — not present in the source.",
            ),
            SuppliedField(
                path="cell.pbc",
                detail="(T, T, T) — required by the target; set by the same recovery choice.",
            ),
        ],
    )
    return updated, assumption


def _bounding_box(positions: np.ndarray, padding: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (orthorhombic lattice, translation) for an axis-aligned box of ``positions`` with
    ``padding`` on every side. Atoms are shifted by ``-min + padding`` so they sit inside the box
    with a ``padding`` margin from each face; the box side per axis is ``extent + 2·padding``."""
    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    extent = hi - lo
    side = extent + 2.0 * padding
    lattice = np.diag(side).astype(np.float64)
    shift = padding - lo
    return lattice, shift


def _frame_with_cell(
    frame: Frame,
    lattice: np.ndarray,
    pbc: tuple[bool, bool, bool],
    *,
    shift: np.ndarray | None = None,
) -> Frame:
    atoms = frame.atoms
    if shift is not None:
        atoms = AtomsBlock(
            symbols=list(atoms.symbols),
            positions=atoms.positions + shift,
            masses=atoms.masses,
        )
    return frame.model_copy(update={"atoms": atoms, "cell": Cell(lattice_vectors=lattice, pbc=pbc)})


def _lattice_from_reference(ref: Any, canonical: CanonicalObject) -> np.ndarray:
    """Borrow a 3×3 lattice from a second parsed structure (``upload_reference``, Part 4 §3.3).

    The reference is a full ``CanonicalObject`` the caller (CLI) parsed and injected into the choice
    ``parameters``; recovery reads its first frame's lattice after checking it *has* one and that
    its atom count matches the source — the compatibility guard the catalog requires, so a lattice
    is never borrowed from an unrelated structure of a different size."""
    if not isinstance(ref, CanonicalObject):
        raise RecoveryError(
            "missing_lattice 'upload_reference' needs a parsed reference structure in "
            "parameters['reference'] (the CLI supplies it from file=PATH)"
        )
    ref_cell = ref.frames[0].cell
    if ref_cell is None or ref_cell.lattice_vectors is None:
        raise RecoveryError(
            "missing_lattice 'upload_reference': the reference structure has no lattice to borrow"
        )
    src_natoms = canonical.frames[0].atoms.positions.shape[0]
    ref_natoms = ref.frames[0].atoms.positions.shape[0]
    if src_natoms != ref_natoms:
        raise RecoveryError(
            "missing_lattice 'upload_reference': atom-count mismatch — source has "
            f"{src_natoms} atoms, reference has {ref_natoms}"
        )
    return np.asarray(ref_cell.lattice_vectors, dtype=np.float64)


def _as_lattice(raw: Any) -> np.ndarray:
    try:
        lattice = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise RecoveryError(
            f"missing_lattice 'manual_input' lattice is not numeric: {exc}"
        ) from exc
    if lattice.shape != (3, 3):
        raise RecoveryError(
            f"missing_lattice 'manual_input' needs a 3×3 lattice, got shape {lattice.shape}"
        )
    return lattice


def _apply_missing_masses(
    canonical: CanonicalObject,
    aid: str,
    choice: dict[str, Any],
    origin: str,
    scenario: UnresolvedScenario,
) -> tuple[CanonicalObject, AppliedAssumption]:
    """Fabricate the per-atom masses a target requires, or that another recovery (Maxwell–Boltzmann)
    needs to seed a velocity draw (fabricative, Part 4 §3.1, §3.3).

    ``standard_masses`` looks up IUPAC standard atomic weights (a *reported default*);
    ``manual_input`` takes a caller-supplied list. Either way one ``Assumption`` and one
    ``SuppliedField('atoms.masses')`` are recorded — the masses did not exist in the source, so they
    are filed as created, never a silent fill (**P4**). ``scenario.params['emit']`` is ``False``
    when the target cannot store masses (e.g. POSCAR): the masses still feed a chained draw, are in
    ``supplied``, but stay
    out of the write plan (``in_write_plan=False``) so validation does not expect them in the output
    (D47)."""
    code = _choice_code(choice, scenario)
    params = choice.get("parameters", {}) or {}
    symbols = list(canonical.frames[0].atoms.symbols)
    n = len(symbols)
    emit = bool(scenario.params.get("emit", True))

    if code == "standard_masses":
        masses = _standard_masses(symbols)
        report_params: dict[str, Any] = {
            "source": "ASE atomic_masses (IUPAC standard atomic weights)"
        }
        source_desc = "IUPAC standard atomic weights"
    else:  # manual_input
        masses = _as_masses(params.get("masses"), n)
        report_params = {"masses_u": masses.tolist()}
        source_desc = "caller-supplied per-atom masses"

    new_frames = [_frame_with_masses(f, masses) for f in canonical.frames]
    updated = canonical.model_copy(update={"frames": new_frames})
    if emit:
        supplied_detail = (
            f"Per-atom masses fabricated from {source_desc} — not present in the source."
        )
    else:
        supplied_detail = (
            f"Per-atom masses fabricated from {source_desc} to seed velocity initialization; not "
            "written to the target, which cannot store masses."
        )
    assumption = AppliedAssumption(
        id=aid,
        scenario="missing_masses",
        choice=code,
        parameters=report_params,
        origin=origin,
        description=(
            f"Filled masses for {n} atom(s) via {code!r} ({source_desc}). The source expressed no "
            "masses — these are a recorded default, never a silent fill (**P4**)."
        ),
        supplied=[SuppliedField(path="atoms.masses", detail=supplied_detail, in_write_plan=emit)],
    )
    return updated, assumption


def _apply_missing_velocities(
    canonical: CanonicalObject,
    aid: str,
    choice: dict[str, Any],
    origin: str,
    scenario: UnresolvedScenario,
) -> tuple[CanonicalObject, AppliedAssumption]:
    """Fabricate the velocities a target requires or the user asked it to emit (fabricative, Part 4
    §3.1, §3.3).

    Four choices: ``zero_init`` (an explicit rest state — *data* per Part 2 §2 rule 3),
    ``maxwell_boltzmann`` (sampled at ``temperature_K`` with a recorded ``seed``),
    ``upload_reference`` (borrowed from a second structure, shape-checked), and ✳``omit`` (leave
    velocities absent — the only choice that fabricates nothing, offered solely when the target
    field is optional and mode is permissive). Every choice but ``omit`` records one
    ``SuppliedField('dynamics.velocities')``."""
    code = _choice_code(choice, scenario)
    params = choice.get("parameters", {}) or {}
    n = canonical.frames[0].atoms.positions.shape[0]

    if code == "omit":
        # The one choice that fabricates nothing: velocities stay absent (P3). No SuppliedField.
        assumption = AppliedAssumption(
            id=aid,
            scenario="missing_velocities",
            choice="omit",
            parameters={},
            origin=origin,
            description=(
                "Velocity emission omitted: the target's velocity field is optional and the mode "
                "is permissive, so no velocities are fabricated and the field is left absent (P3)."
            ),
        )
        return canonical, assumption

    if code == "zero_init":
        velocities = np.zeros((n, 3), dtype=np.float64)
        report_params: dict[str, Any] = {}
        description = (
            "Velocities initialized to an explicit rest state (all zero). Per Part 2 §2 rule 3 an "
            "all-zero velocity field is *data* (the system stated at rest), distinct from absence, "
            "so it is a recorded choice, never a silent fill."
        )
    elif code == "maxwell_boltzmann":
        temperature_k = _as_temperature(params.get("temperature_K"))
        seed = params.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise RecoveryError(
                f"missing_velocities 'maxwell_boltzmann' needs an integer seed, got {seed!r}"
            )
        masses = canonical.frames[0].atoms.masses
        if masses is None:
            raise RecoveryError(
                "missing_velocities 'maxwell_boltzmann' needs per-atom masses; supply them via a "
                "missing_masses recovery choice (they chain in dependency order)"
            )
        velocities = _maxwell_boltzmann(np.asarray(masses, dtype=np.float64), temperature_k, seed)
        report_params = {"temperature_K": temperature_k, "seed": seed}
        description = (
            f"Velocities sampled from a Maxwell–Boltzmann distribution at {temperature_k} K "
            f"(seed {seed}); each Cartesian component drawn independently with variance kT/mᵢ. The "
            "raw per-atom sample is emitted unchanged — no center-of-mass drift is removed, since "
            "that would be an unrequested transformation contrary to the transparent-converter "
            "mission (D43). Temperature and seed are recorded so the draw is exactly reproducible "
            "(R11)."
        )
    else:  # upload_reference
        velocities = _velocities_from_reference(params.get("reference"), n)
        report_params = {"reference_atom_count": n}
        description = (
            "Velocities taken from a second uploaded reference structure whose atom count matches "
            "the source. The source expressed no velocities — these are borrowed from the "
            "reference, not present in the source."
        )

    new_frames = [_frame_with_velocities(f, velocities) for f in canonical.frames]
    updated = canonical.model_copy(update={"frames": new_frames})
    assumption = AppliedAssumption(
        id=aid,
        scenario="missing_velocities",
        choice=code,
        parameters=report_params,
        origin=origin,
        description=description,
        supplied=[
            SuppliedField(
                path="dynamics.velocities",
                detail="Per-atom velocities fabricated by recovery — not present in the source.",
            )
        ],
    )
    return updated, assumption


def _maxwell_boltzmann(masses: np.ndarray, temperature_k: float, seed: int) -> np.ndarray:
    """Sample velocities (Å/fs) from a Maxwell–Boltzmann distribution at ``temperature_k`` (K).

    Each atom's Cartesian component is an independent Gaussian with standard deviation
    ``sqrt(kB·T/mᵢ)``, so the per-component variance is exactly ``kT/mᵢ``. Determinism is by a local
    ``np.random.default_rng(seed)`` — never the global ``np.random`` state (D45). The raw sample is
    returned unchanged: no center-of-mass drift removal, no temperature rescaling (D43). The unit
    factor is ``ase.units.fs`` — the same ASE-velocity → Å/fs conversion the extXYZ parser uses — so
    no hand-rolled constant can drift from the rest of the codebase."""
    rng = np.random.default_rng(seed)
    sigma = np.sqrt(ase_units.kB * temperature_k / masses) * ase_units.fs
    sample: np.ndarray = rng.standard_normal((masses.shape[0], 3)) * sigma[:, None]
    return sample


def _standard_masses(symbols: list[str]) -> np.ndarray:
    """IUPAC standard atomic weights (u) for ``symbols`` from ``ase.data.atomic_masses`` (D44). The
    reserved unknown species ``"X"`` (Z = 0) has no standard weight and is refused — the caller must
    supply masses via ``manual_input``."""
    masses = np.empty(len(symbols), dtype=np.float64)
    for i, sym in enumerate(symbols):
        z = atomic_number(sym)
        if z == 0:
            raise RecoveryError(
                "missing_masses 'standard_masses' has no standard weight for the unknown species "
                f"'X' at atom {i}; supply masses via manual_input"
            )
        masses[i] = float(ase.data.atomic_masses[z])
    return masses


def _as_masses(raw: Any, n: int) -> np.ndarray:
    try:
        masses = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise RecoveryError(f"missing_masses 'manual_input' masses are not numeric: {exc}") from exc
    if masses.shape != (n,):
        raise RecoveryError(
            f"missing_masses 'manual_input' needs {n} masses (one per atom); got {masses.shape}"
        )
    if bool(np.any(masses <= 0)):
        raise RecoveryError("missing_masses 'manual_input' masses must all be positive")
    return masses


def _as_temperature(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise RecoveryError(
            f"missing_velocities 'maxwell_boltzmann' needs a numeric temperature_K, got {raw!r}"
        )
    temperature_k = float(raw)
    if temperature_k <= 0:
        raise RecoveryError(
            "missing_velocities 'maxwell_boltzmann' temperature_K must be positive, got "
            f"{temperature_k}"
        )
    return temperature_k


def _velocities_from_reference(ref: Any, n: int) -> np.ndarray:
    """Borrow per-atom velocities from a second parsed structure (``upload_reference``, Part 4
    §3.3), shape-checked against the source atom count so velocities are never taken from a
    structure of a different size."""
    if not isinstance(ref, CanonicalObject):
        raise RecoveryError(
            "missing_velocities 'upload_reference' needs a parsed reference structure in "
            "parameters['reference'] (the CLI supplies it from file=PATH)"
        )
    ref_vel = ref.frames[0].dynamics.velocities
    if ref_vel is None:
        raise RecoveryError(
            "missing_velocities 'upload_reference': the reference structure has no velocities to "
            "borrow"
        )
    ref_vel = np.asarray(ref_vel, dtype=np.float64)
    if ref_vel.shape != (n, 3):
        raise RecoveryError(
            "missing_velocities 'upload_reference': shape mismatch — source has "
            f"{n} atoms, reference velocities are shape {ref_vel.shape}"
        )
    return ref_vel


def _frame_with_masses(frame: Frame, masses: np.ndarray) -> Frame:
    atoms = frame.atoms
    return frame.model_copy(
        update={
            "atoms": AtomsBlock(
                symbols=list(atoms.symbols), positions=atoms.positions, masses=masses
            )
        }
    )


def _frame_with_velocities(frame: Frame, velocities: np.ndarray) -> Frame:
    new_dynamics = frame.dynamics.model_copy(update={"velocities": velocities})
    return frame.model_copy(update={"dynamics": new_dynamics})
