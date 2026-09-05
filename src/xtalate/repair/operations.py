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

from xtalate.repair._reindex import reindex_per_atom
from xtalate.repair.contract import (
    REPAIR_BLOCK_MISSING_LATTICE,
    TRANSFORMATIVE_HAZARD,
    RepairBlock,
    RepairError,
    RepairHazard,
    RepairOperation,
)
from xtalate.schema import CanonicalObject, Frame
from xtalate.schema.cell import to_cartesian, to_fractional


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

    def _permutation(self, obj: CanonicalObject, parameters: dict[str, Any]) -> list[int]:
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
        if perm == list(range(n)):
            return (
                "Regrouped atoms by element (first-appearance order, stable within each "
                "element): the source was already element-grouped, so the identity "
                "permutation was applied — no order changed."
            )
        return (
            "Regrouped atoms by element (first-appearance order, stable within each "
            "element) across every frame; the recorded permutation map recovers the "
            "original order exactly."
        )


def builtin_repair_operations() -> list[RepairOperation]:
    """The explicit first-party repair-operation list (M64). Third-party repairs are declined
    for v1.7 (impl-plan §4 rule 4); center/dedupe register here later in M65, reorder now."""
    return [IdentityRepair(), WrapIntoCell(), SpeciesReorder()]
