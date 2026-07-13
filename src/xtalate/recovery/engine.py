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

import numpy as np

from xtalate.recovery.scenarios import (
    SCENARIO_HAZARD,
    UnresolvedScenario,
    available_options,
)
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame

# Resolution order (Part 4 §3.3): frame_selection first (a bounding box is computed on the chosen
# frame), then constraint projection (frame-independent), then the fabricated lattice.
_DEP_ORDER = ("frame_selection", "constraint_representation", "missing_lattice")


class RecoveryError(ValueError):
    """A preset named an option that is not offered for this pair, or omitted a required
    parameter. Distinct from a *refusal* (no choice supplied): a refusal is a legitimate
    conversion outcome (Part 4 §4); an invalid preset is a caller error."""


@dataclass
class SuppliedField:
    """One canonical field a fabricative recovery wrote into the object (Part 4 §2, `supplied`)."""

    path: str
    detail: str | None = None


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
        removed=[
            FrameDrop(
                path="atoms.positions",
                reason="Target format stores a single structure (max_frames = 1).",
                detail=f"{dropped} of {n} frames dropped; frame {index} retained per {aid}.",
            )
        ],
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
