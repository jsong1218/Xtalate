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

from xtalate.repair.contract import (
    REPAIR_BLOCK_MISSING_LATTICE,
    TRANSFORMATIVE_HAZARD,
    RepairBlock,
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


def builtin_repair_operations() -> list[RepairOperation]:
    """The explicit first-party repair-operation list (M64). Third-party repairs are declined
    for v1.7 (impl-plan §4 rule 4); center/dedupe/reorder register here in M65."""
    return [IdentityRepair(), WrapIntoCell()]
