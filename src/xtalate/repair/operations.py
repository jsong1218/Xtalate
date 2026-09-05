"""The concrete repair operations (v1.7 M64).

The operation set is **closed at four for the whole version** — wrap-into-cell (M64), center,
deduplicate, species reorder (M65) — and ``identity``, which is **not** a fifth scientific
operation: it is the reference implementation of the ``RepairOperation`` contract (M64-S1),
used to prove the recording spine and the reproducibility harness before the hard operation
(wrap) lands. ``builtin_repair_operations()`` is the explicit first-party list a higher layer
assembles into a lookup table (the parsers/exporters precedent); third-party repair operations
are a future SDK seam explicitly declined for v1.7 (impl-plan §4 rule 4).

Wrap-into-cell (M64-S2) is the version's flagship: the one operation with a physics-losing
failure mode (R5 — unwrapped diffusion paths are destroyed), carried as the D251
*transformative* hazard class: explicit request **plus** a report warning naming exactly what
is unrecoverable. It composes with recovery — a cell-less object refuses via the existing
``missing_lattice`` scenario rather than fabricating a box (D43).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from xtalate.repair._reindex import reindex_per_atom
from xtalate.repair.contract import (
    REPAIR_BLOCK_MISSING_LATTICE,
    SELECTIVE_REDUCTIVE_HAZARD,
    TRANSFORMATIVE_HAZARD,
    RepairBlock,
    RepairError,
    RepairHazard,
    RepairOperation,
)
from xtalate.schema import CanonicalObject, Frame
from xtalate.schema.cell import to_cartesian, to_fractional

#: The deduplicate plan: (survivor indices ascending, removed indices ascending, metric,
#: threshold) — the deterministic function of threshold + source positions the report replays.
_DedupePlan = tuple[list[int], list[int], str, float]


class IdentityRepair(RepairOperation):
    """The contract's reference operation (M64-S1): applies no scientific change.

    Exists to prove the recording spine — an ordered, recorded, reproducible repair — before the
    hard operation lands. It records exactly what was requested (including any parameters) and
    states plainly that nothing changed; it is not a fifth scientific operation.
    """

    operation = "identity"

    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        return obj

    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        return (
            "Identity repair (the reference operation): applied for the record — no scientific "
            "value changed."
        )


#: The R5 hazard statement (D251): wrapping destroys the unwrapped trajectory information.
#: Rendered as a ``ReportWarning(source="repair")`` — the report states the loss in plain
#: language, exactly like any other loss (corollary 1 of the version's contract).
WRAP_DISCARDS_UNWRAPPED_PATHS = RepairHazard(
    code="WRAP_DISCARDS_UNWRAPPED_PATHS",
    message=(
        "wrapping discards unwrapped trajectory information — diffusion paths across periodic "
        "boundaries are not recoverable from the wrapped file"
    ),
)

#: Cells at or below this volume (Å³) cannot host a minimum-image wrap — far below any physical
#: cell, far above float noise on a real one; anything under it is a degenerate/zero-volume box
#: (a singular lattice cannot be inverted into fractional coordinates honestly).
_MIN_CELL_VOLUME = 1e-12


def _frame_lattice(frame: Frame) -> np.ndarray | None:
    """The frame's usable lattice, or ``None`` when the frame has no cell / a degenerate one."""
    if frame.cell is None:
        return None
    lattice = np.asarray(frame.cell.lattice_vectors, dtype=float)
    if lattice.shape != (3, 3):
        return None
    volume = np.linalg.det(lattice)
    if not np.isfinite(volume) or abs(volume) <= _MIN_CELL_VOLUME:
        return None
    return lattice


class WrapIntoCell(RepairOperation):
    """Minimum-image wrap of atom positions into the simulation cell, **per frame** (M64-S2).

    Each frame's positions are converted to fractional coordinates against that frame's own
    lattice, folded into ``[0, 1)``, and converted back to Cartesian Å — the standard minimum-
    image convention (``cart = frac @ lattice``, the same relationship the parsers/exporters
    use, ``xtalate.schema.cell``). **Deterministic boundary handling:** folding is
    ``np.mod(frac, 1.0)``, so a coordinate exactly on a cell face lands the same way on every
    run — every integer fractional coordinate (``1.0``, ``2.0``, ``-1.0``, …) maps to exactly
    ``0.0``, ``0.5`` stays ``0.5``, and every other value folds into ``[0, 1)``.

    Transformative hazard (D251): wrapping discards the unwrapped trajectory information —
    diffusion paths across periodic boundaries are unrecoverable from the wrapped file — stated
    as the ``WRAP_DISCARDS_UNWRAPPED_PATHS`` report warning on every application. A frame with
    no cell (or a degenerate/zero-volume one) **blocks** through the existing
    ``missing_lattice`` recovery scenario: wrap invents no box (D43).
    """

    operation = "wrap_into_cell"
    hazard_class = TRANSFORMATIVE_HAZARD
    hazards = (WRAP_DISCARDS_UNWRAPPED_PATHS,)

    def block(self, obj: CanonicalObject, parameters: dict[str, Any]) -> RepairBlock | None:
        for frame in obj.frames:
            if _frame_lattice(frame) is None:
                if frame.cell is None:
                    detail = (
                        f"frame {frame.index} declares no simulation cell — wrap-into-cell needs "
                        "a lattice to wrap into; supply one through recovery (missing_lattice) "
                        "or convert without this repair"
                    )
                else:
                    detail = (
                        f"frame {frame.index} declares a singular/zero-volume cell that cannot "
                        "host a minimum-image wrap; supply a usable lattice through recovery "
                        "(missing_lattice) or convert without this repair"
                    )
                return RepairBlock(
                    operation=self.operation,
                    reason=REPAIR_BLOCK_MISSING_LATTICE,
                    path="cell.lattice_vectors",
                    detail=detail,
                )
        return None

    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        frames: list[Frame] = []
        for frame in obj.frames:
            lattice = _frame_lattice(frame)
            assert lattice is not None  # block() refused a cell-less/degenerate frame already.
            positions = np.asarray(frame.atoms.positions, dtype=float)
            frac = to_fractional(positions, lattice)
            wrapped = to_cartesian(np.mod(frac, 1.0), lattice)
            frames.append(
                frame.model_copy(
                    update={"atoms": frame.atoms.model_copy(update={"positions": wrapped})}
                )
            )
        return obj.model_copy(update={"frames": frames})

    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        n_frames = len(obj.frames)
        n_atoms = obj.frames[0].atoms.positions.shape[0]
        return (
            f"Wrapped all atom positions into the simulation cell (minimum-image convention) "
            f"across {n_frames} frame(s), {n_atoms} atoms per frame — the unwrapped trajectory "
            "is not recoverable from the wrapped file."
        )


#: The order-changed advisory (D252). Reordering is fully recoverable — the recorded
#: permutation map reconstructs the original order exactly — so this is an **advisory**
#: for downstream tools that key on atom order (Part 5 §2's ``ATOM_ORDER_CHANGED``),
#: not a transformative-loss statement: nothing is lost, so ``species_reorder`` declares
#: no hazard class, and the row is suppressed when the permutation is the identity (an
#: application that changed nothing must not claim an order change).
ATOM_ORDER_CHANGED = RepairHazard(
    code="ATOM_ORDER_CHANGED",
    message=(
        "atom order changed — atoms are regrouped by element; the original order is fully "
        "recoverable from the recorded permutation map, but downstream tools that key on "
        "atom order may need re-association"
    ),
)


def _element_grouping_permutation(symbols: list[str]) -> list[int]:
    """The species-reorder permutation: atoms grouped by element in first-appearance order.

    Mirrors the exporters' grouping rule (``exporters._common.group_by_element`` — the
    same first-occurrence element order, stable within an element so atoms of one
    element keep their relative order), reimplemented here because ``repair`` may not
    import ``exporters`` (layering, Part 1 §5.1). A lockstep test pins the two to each
    other, so the repaired object is exactly the object an element-grouping exporter
    (POSCAR) expects — the exporter's own ``atom_permutation`` then applies on top as
    usual (D20), with no double-counting.
    """
    order: list[str] = []
    groups: dict[str, list[int]] = {}
    for i, sym in enumerate(symbols):
        if sym not in groups:
            groups[sym] = []
            order.append(sym)
        groups[sym].append(i)
    return [i for sym in order for i in groups[sym]]


class SpeciesReorder(RepairOperation):
    """Regroup atoms by element (first-appearance order, stable within each element), via one
    frame-invariant permutation applied to **every** frame (M65-S1; D252).

    Non-destructive: a permutation is fully reversible from its map, so the operation
    declares **no hazard class** — nothing is lost, no value is changed. It records the
    computed permutation map as its parameters (the D23 ``atom_permutation`` seam, now
    user-invokable — and the exact datum the reproducibility harness re-derives from),
    and emits the ``ATOM_ORDER_CHANGED`` advisory as a ``source="repair"`` warning for
    downstream tools that key on atom order — **suppressed when the source is already
    element-grouped**, because the identity permutation changes nothing and the advisory
    would be a lie. The permutation is computed **once** from frame 0's symbols and
    applied identically to every frame (atom identity is frame-invariant, so element
    grouping is too — the property that makes reorder safe on trajectories while dedupe
    is not). Every per-atom array and constraint reference follows the same map through
    the shared reindex spine (``repair._reindex``, D252) — a half-reindexed object is
    impossible by construction.
    """

    operation = "species_reorder"
    hazard_class = None  # Non-destructive: a recorded permutation fully recovers the order.
    hazards = (ATOM_ORDER_CHANGED,)

    #: Single-entry compute cache for one application. The engine calls ``apply``,
    #: ``recorded_parameters``, ``hazards_for`` and ``describe`` back-to-back on the *same*
    #: ``(obj, parameters)`` (engine.py); this memo derives the permutation once and reuses it,
    #: keyed by object **identity** (``is``) so it is always the datum computed for exactly this
    #: call — never a stale hit. Instances are built fresh per ``apply_repairs``
    #: (``builtin_repair_operations``), so the cache lives only for one request and preserves the
    #: contract's purity/determinism (same inputs → same output).
    _perm_cache: tuple[CanonicalObject, dict[str, Any], list[int]] | None = None

    def _permutation(self, obj: CanonicalObject, parameters: dict[str, Any]) -> list[int]:
        cached = self._perm_cache
        if cached is not None and cached[0] is obj and cached[1] is parameters:
            return cached[2]
        perm = self._compute_permutation(obj, parameters)
        self._perm_cache = (obj, parameters, perm)
        return perm

    def _compute_permutation(self, obj: CanonicalObject, parameters: dict[str, Any]) -> list[int]:
        n = obj.frames[0].atoms.positions.shape[0]
        supplied = parameters.get("permutation")
        if supplied is not None:
            perm = [int(i) for i in supplied]
            if sorted(perm) != list(range(n)):
                raise RepairError(
                    f"species_reorder: the recorded permutation must rearrange "
                    f"range({n}) exactly once, got {supplied!r}"
                )
            return perm
        return _element_grouping_permutation(obj.frames[0].atoms.symbols)

    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        return reindex_per_atom(obj, self._permutation(obj, parameters), operation=self.operation)

    def recorded_parameters(
        self, obj: CanonicalObject, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        # The permutation actually applied — the completeness half of the reproducibility
        # contract: apply(source, recorded_parameters) re-derives byte-identically.
        return {"permutation": self._permutation(obj, parameters)}

    def hazards_for(self, obj: CanonicalObject, parameters: dict[str, Any]) -> list[RepairHazard]:
        n = obj.frames[0].atoms.positions.shape[0]
        if self._permutation(obj, parameters) == list(range(n)):
            return []  # Identity application: nothing changed, the advisory would be a lie.
        return list(self.hazards)

    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        perm = self._permutation(obj, parameters)
        n = obj.frames[0].atoms.positions.shape[0]
        # Only the computed path is element-grouping; a caller-supplied permutation is an
        # arbitrary rearrangement (validated only to be a permutation of range(n), not that
        # it groups by element), so the report must not claim an element regroup it did not do.
        supplied = parameters.get("permutation") is not None
        if perm == list(range(n)):
            if supplied:
                return (
                    "Reordered atoms by the supplied permutation map: it is the identity "
                    "permutation, so no atom order changed."
                )
            return (
                "Regrouped atoms by element (first-appearance order, stable within each "
                "element): the source was already element-grouped, so the identity "
                "permutation was applied — no order changed."
            )
        if supplied:
            return (
                "Reordered atoms by the supplied permutation map across every frame; the "
                "recorded permutation map recovers the original order exactly."
            )
        return (
            "Regrouped atoms by element (first-appearance order, stable within each "
            "element) across every frame; the recorded permutation map recovers the "
            "original order exactly."
        )


#: The center hazard statement (D253). Centering translates the whole structure — the
#: original absolute frame of reference is unrecoverable from the centered file, though all
#: relative geometry is preserved. This is the mild end of the transformative class (D251):
#: values change in place, but only by a rigid translation, so the warning says exactly that.
CENTER_DISCARDS_ABSOLUTE_POSITION = RepairHazard(
    code="CENTER_DISCARDS_ABSOLUTE_POSITION",
    message=(
        "centering translates the whole structure — the original position relative to the "
        "source's coordinate origin is not recoverable from the centered file (all relative "
        "geometry is preserved)"
    ),
)

#: The two ways to name the point to move, and the two named places it can go (M65-S2; D253).
#: An explicit ``[x, y, z]`` Å coordinate is also a legal target. Both parameters are required
#: with **no default** (P4: which point and where it lands are scientific judgments).
_CENTER_REFERENCES = ("centroid", "cell_center")
_CENTER_NAMED_TARGETS = ("origin", "cell_center")


def _center_reference(parameters: dict[str, Any]) -> str:
    reference = parameters.get("reference")
    if not isinstance(reference, str) or reference not in _CENTER_REFERENCES:
        raise RepairError(
            f"center requires a reference of {_CENTER_REFERENCES} (the point of the "
            f"structure to move), got {reference!r} — no default (P4)"
        )
    return reference


def _center_target(parameters: dict[str, Any]) -> tuple[str, np.ndarray | None]:
    """Validate the target: ``("origin", None)``, ``("cell_center", None)``, or
    ``("explicit", [x, y, z])`` in Å. Raises ``RepairError`` naming the choice when absent or
    incoherent (P4: no default)."""
    target = parameters.get("target")
    if target in _CENTER_NAMED_TARGETS:
        return target, None
    if isinstance(target, (list, tuple)) and len(target) == 3:
        try:
            vec = np.asarray(target, dtype=float)
        except (TypeError, ValueError):
            vec = np.array([np.nan, np.nan, np.nan])
        if not np.all(np.isfinite(vec)):
            raise RepairError(
                f"center target [x, y, z] must be three finite Å coordinates, got {target!r}"
            )
        return "explicit", vec
    raise RepairError(
        f"center requires a target of {_CENTER_NAMED_TARGETS} or an explicit [x, y, z] Å "
        f"coordinate (where the reference point should land), got {target!r} — no default (P4)"
    )


def _centroid(positions: NDArray[np.float64]) -> NDArray[np.float64]:
    """The unweighted geometric mean of positions — M65 ships no mass-weighted center-of-mass
    mode (D253): mass-weighting would need masses that may be ``None``, and fabricating IUPAC
    weights purely to center would violate P4."""
    return positions.mean(axis=0)


def _cell_center(lattice: NDArray[np.float64]) -> NDArray[np.float64]:
    """The cell's geometric center, ½(a+b+c) from the frame's own lattice (row-vector
    convention: rows are a, b, c)."""
    return np.asarray(0.5 * (lattice[0] + lattice[1] + lattice[2]))


class Center(RepairOperation):
    """Translate a stated reference point of the structure to a stated target, **per frame**
    (M65-S2; D253).

    ``reference`` ∈ {``"centroid"`` (the unweighted geometric mean of that frame's
    positions), ``"cell_center"`` (½(a+b+c) of that frame's lattice)}; ``target`` ∈
    {``"origin"``, ``"cell_center"``, an explicit ``[x, y, z]`` Å coordinate}. **Both are
    required, no default** (P4). Per frame, the reference point is computed from **that
    frame's own** positions/cell and the constant shift ``target − reference`` is added to
    every position — deterministic, no randomness, ``model_copy``. **Positions only:**
    velocities/forces/charges are translation-invariant and are **not** touched.

    Transformative hazard (D251): centering discards the original absolute frame of
    reference — the ``CENTER_DISCARDS_ABSOLUTE_POSITION`` warning names exactly that (the
    mild end of the class: relative geometry is preserved). A ``cell_center`` reference or
    target on a frame with no usable cell **blocks** through the existing
    ``missing_lattice`` recovery (the wrap precedent): center invents no box (D43).
    """

    operation = "center"
    hazard_class = TRANSFORMATIVE_HAZARD
    hazards = (CENTER_DISCARDS_ABSOLUTE_POSITION,)

    def block(self, obj: CanonicalObject, parameters: dict[str, Any]) -> RepairBlock | None:
        reference = _center_reference(parameters)
        target, _ = _center_target(parameters)
        if reference != "cell_center" and target != "cell_center":
            return None  # Centroid/origin need no cell.
        for frame in obj.frames:
            if _frame_lattice(frame) is None:
                if frame.cell is None:
                    detail = (
                        f"frame {frame.index} declares no simulation cell — a cell_center "
                        "reference or target needs a lattice; supply one through recovery "
                        "(missing_lattice) or convert without this repair"
                    )
                else:
                    detail = (
                        f"frame {frame.index} declares a singular/zero-volume cell whose "
                        "center is not well-defined; supply a usable lattice through recovery "
                        "(missing_lattice) or convert without this repair"
                    )
                return RepairBlock(
                    operation=self.operation,
                    reason=REPAIR_BLOCK_MISSING_LATTICE,
                    path="cell.lattice_vectors",
                    detail=detail,
                )
        return None

    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        reference = _center_reference(parameters)
        target, explicit_target = _center_target(parameters)
        frames: list[Frame] = []
        for frame in obj.frames:
            positions = np.asarray(frame.atoms.positions, dtype=float)
            ref = _centroid(positions) if reference == "centroid" else _frame_lattice(frame)
            assert ref is not None  # block() refused a cell-less frame already.
            if reference == "cell_center":
                ref = _cell_center(ref)
            if explicit_target is not None:
                target_point = explicit_target
            elif target == "cell_center":
                lattice = _frame_lattice(frame)
                assert lattice is not None  # block() refused a cell-less frame already.
                target_point = _cell_center(lattice)
            else:  # target == "origin"
                target_point = np.zeros(3)
            shift = target_point - ref
            frames.append(
                frame.model_copy(
                    update={
                        "atoms": frame.atoms.model_copy(update={"positions": positions + shift})
                    }
                )
            )
        return obj.model_copy(update={"frames": frames})

    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        reference = _center_reference(parameters)
        target, explicit = _center_target(parameters)
        if explicit is not None:
            target_desc = f"[{explicit[0]:g}, {explicit[1]:g}, {explicit[2]:g}] Å"
        else:
            target_desc = str(target)
        return (
            f"Centered the structure per frame: translated the {reference} to {target_desc} — "
            "positions only (velocities/forces/charges are translation-invariant); the "
            "original absolute origin is not recoverable from the centered file."
        )


#: The dedupe loss-statement code (D254). The full warning is built per application — it
#: names the count removed, which only the application knows — so ``hazards_for`` returns a
#: fresh ``RepairHazard`` with this stable code, or nothing when no atom was removed (a
#: no-op repair must not claim a loss).
DEDUPE_REMOVED_ATOMS = RepairHazard(
    code="DEDUPE_REMOVED_ATOMS",
    message=(  # base text; the per-application row adds the count
        "deduplicate removed atoms closer than the requested threshold — the Assumption "
        "enumerates exactly which (index + species) were removed, and they are not "
        "recoverable from the output"
    ),
)


def _dedupe_threshold(parameters: dict[str, Any]) -> float:
    """The required positive ``distance_threshold`` (Å) — no default (P4): a tolerance is a
    scientific judgment about the data."""
    threshold = parameters.get("distance_threshold")
    if threshold is None:
        raise RepairError(
            "deduplicate requires a positive distance_threshold (Å); a tolerance is a "
            "scientific judgment about the data, so there is no default"
        )
    try:
        value = float(threshold)
    except (TypeError, ValueError):
        value = np.nan
    if not np.isfinite(value) or value <= 0.0:
        raise RepairError(
            "deduplicate requires a positive distance_threshold (Å), got "
            f"{threshold!r}; a tolerance is a scientific judgment about the data, so "
            "there is no default"
        )
    return value


def _pairwise_distances(
    frame: Frame,
) -> tuple[np.ndarray, str]:
    """The ``(n, n)`` pairwise distance matrix and the metric used to compute it.

    Minimum-image wrapping is applied **only along the axes the frame declares periodic**
    (``cell.pbc``): the fractional difference is wrapped to ``[-0.5, 0.5)`` via ``d - round(d)``
    on those axes and left unwrapped on the rest. A frame with no usable lattice — **or one
    whose ``pbc`` is all False** (a cluster in a bounding box, a gas-phase molecule that still
    carries a box) — uses plain Cartesian distance: a cell's *presence* is not periodicity
    (P3 — ``pbc`` is the information), so no report may claim periodic boundary conditions for a
    structure that declares none, and no atom may be wrapped across a boundary that does not
    physically exist. The metric string states exactly which convention was used (D254), naming
    the periodic axes when they are a strict subset."""
    positions = np.asarray(frame.atoms.positions, dtype=float)
    lattice = _frame_lattice(frame)
    pbc = tuple(frame.cell.pbc) if frame.cell is not None else (False, False, False)
    if lattice is not None and any(pbc):
        frac = to_fractional(positions, lattice)
        dfrac = frac[:, None, :] - frac[None, :, :]
        # Minimum image in fractional coordinates, but only along declared-periodic axes;
        # a non-periodic axis keeps its raw (unwrapped) difference.
        periodic = np.array(pbc, dtype=bool)
        dfrac = np.where(periodic, dfrac - np.round(dfrac), dfrac)
        cart = dfrac @ lattice
        if all(pbc):
            metric = "minimum-image under the simulation cell's periodic boundary conditions"
        else:
            axes = ", ".join(name for name, on in zip("abc", pbc, strict=True) if on)
            metric = (
                f"minimum-image along the periodic lattice direction(s) {axes} "
                "(the cell's other directions are non-periodic)"
            )
    else:
        cart = positions[:, None, :] - positions[None, :, :]
        metric = (
            "plain Cartesian distance (the cell declares no periodic directions)"
            if lattice is not None
            else "plain Cartesian distance (no simulation cell)"
        )
    return np.sqrt(np.sum(cart * cart, axis=-1)), metric


class Deduplicate(RepairOperation):
    """Remove atoms closer than a **user-supplied threshold**, single-structure only
    (M65-S3; D254).

    ``distance_threshold`` (Å) is required with **no default** (P4: a tolerance is a
    scientific judgment about the data). Removal is a **greedy single sweep in ascending
    original index**: an atom is removed when it lies within the threshold of an
    already-surviving atom, so the **lowest original index survives** each such group (this
    is a greedy survivor sweep, not a mutual/transitive clustering — a chain A–B–C where the
    ends are not themselves within threshold keeps both ends). The survivor keeps its own
    values **verbatim** (no merging/averaging: an averaged pseudo-atom would fabricate
    positions/charges the source never held). Distances are minimum-image **only along the
    axes the cell declares periodic** (``cell.pbc``), and plain Cartesian when the frame has
    no usable cell *or* declares no periodic directions (a cell's presence is not
    periodicity, P3) — the recorded parameters and description state **which** was used. The
    removal is applied
    through the shared reindex spine on the survivor indices, so every per-atom category
    follows the same selection and a removed atom referenced by a constraint refuses
    (``RepairError`` — never a silently dropped reference). The Assumption parameters
    enumerate the removed atoms by ``{index, symbol}`` (the report answers *which* atoms,
    exactly, not just how many).

    **Selective-reductive** (``HazardClass``'s vocabulary, D254): dedupe removes real
    atoms — a reductive loss, not a transformative one — and the report warns with
    ``DEDUPE_REMOVED_ATOMS`` (the count removed) on every application that removed
    something. A trajectory **refuses** (``RepairError``): inter-atom distances change
    frame to frame, a per-frame removal set would violate the trajectory-wide
    constant-atom-count invariant and the object-level ``custom_per_atom``, and atoms
    transiently within a threshold is physics, not a defect — "duplicate atoms" is a
    structure-cleanup concern.
    """

    operation = "deduplicate"
    hazard_class = SELECTIVE_REDUCTIVE_HAZARD
    hazards = (DEDUPE_REMOVED_ATOMS,)

    #: Single-entry compute cache for one application (see ``SpeciesReorder._perm_cache``): the
    #: engine calls ``apply``/``recorded_parameters``/``hazards_for``/``describe`` back-to-back
    #: on the same ``(obj, parameters)``, and the O(n²) pairwise-distance plan is derived once
    #: and reused, keyed by object **identity**. Fresh instance per request → per-request memo.
    _plan_cache: tuple[CanonicalObject, dict[str, Any], _DedupePlan] | None = None

    def _plan(self, obj: CanonicalObject, parameters: dict[str, Any]) -> _DedupePlan:
        cached = self._plan_cache
        if cached is not None and cached[0] is obj and cached[1] is parameters:
            return cached[2]
        plan = self._compute_plan(obj, parameters)
        self._plan_cache = (obj, parameters, plan)
        return plan

    def _compute_plan(self, obj: CanonicalObject, parameters: dict[str, Any]) -> _DedupePlan:
        """(survivor indices ascending, removed indices ascending, metric, threshold). The
        removal set is a deterministic function of threshold + source positions, so the
        recorded parameters replay it exactly."""
        threshold = _dedupe_threshold(parameters)
        if obj.frame_count > 1:
            raise RepairError(
                "deduplicate operates on a single structure only — this object has "
                f"{obj.frame_count} frames; inter-atom distances change frame to frame, "
                "and a per-frame removal set would violate the trajectory-wide "
                "constant-atom-count invariant (and the object-level custom_per_atom), "
                "so a trajectory cannot be deduplicated"
            )
        frame = obj.frames[0]
        n = frame.atoms.positions.shape[0]
        dist, metric = _pairwise_distances(frame)
        removed: set[int] = set()
        for i in range(n):
            if i in removed:
                continue
            for j in range(i + 1, n):
                if j not in removed and dist[i, j] < threshold:
                    removed.add(j)
        survivors = [i for i in range(n) if i not in removed]
        return survivors, sorted(removed), metric, threshold

    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        survivors, _, _, _ = self._plan(obj, parameters)
        return reindex_per_atom(obj, survivors, operation=self.operation)

    def recorded_parameters(
        self, obj: CanonicalObject, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        # The complete record: the threshold that was applied, the metric used, and the
        # exact removed set by {index, symbol} — the reproducibility harness replays the
        # threshold and re-derives the same removal set deterministically.
        _, removed, metric, threshold = self._plan(obj, parameters)
        symbols = obj.frames[0].atoms.symbols
        return {
            "distance_threshold": threshold,
            "metric": metric,
            "removed_atoms": [{"index": i, "symbol": symbols[i]} for i in removed],
        }

    def hazards_for(self, obj: CanonicalObject, parameters: dict[str, Any]) -> list[RepairHazard]:
        _, removed, _, _ = self._plan(obj, parameters)
        if not removed:
            return []  # Nothing removed — no loss; a no-op repair must not claim one.
        return [
            RepairHazard(
                code=DEDUPE_REMOVED_ATOMS.code,
                message=(
                    f"deduplicate removed {len(removed)} atom(s) closer than the "
                    "requested threshold — the Assumption enumerates exactly which "
                    "(index + species) were removed, and they are not recoverable from "
                    "the output"
                ),
            )
        ]

    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        _, removed, metric, threshold = self._plan(obj, parameters)
        if not removed:
            return (
                f"Deduplicated the structure: no atoms were closer than {threshold:g} Å "
                f"({metric}) — nothing removed (a recorded no-op repair)."
            )
        return (
            f"Deduplicated the structure: removed {len(removed)} atom(s) closer than "
            f"{threshold:g} Å ({metric}); the survivor of each cluster keeps its own "
            "values verbatim and the Assumption enumerates exactly which atoms were "
            "removed."
        )


def builtin_repair_operations() -> list[RepairOperation]:
    """The explicit first-party repair-operation list — the **closed set of four** (+ the
    ``identity`` reference op), complete at M65-S3 (D254). Third-party repairs are declined
    for v1.7 (impl-plan §4 rule 4)."""
    return [
        IdentityRepair(),
        WrapIntoCell(),
        SpeciesReorder(),
        Center(),
        Deduplicate(),
    ]
