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

**Dependency ordering (Part 4 §3.3).** ``frame_selection`` is resolved before ``missing_lattice``
because a ``bounding_box`` lattice is computed on the *selected* frame's positions. Assumptions are
numbered ``A1, A2, …`` in application order, matching the worked example (A1 = frame_selection,
A2 = missing_lattice; Part 4 §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from chembridge.recovery.scenarios import (
    SCENARIO_HAZARD,
    UnresolvedScenario,
    available_options,
)
from chembridge.schema import AtomsBlock, CanonicalObject, Cell, Frame

# Resolution order (Part 4 §3.3): a bounding box is computed on the frame chosen by
# frame_selection, so frame_selection must run first.
_DEP_ORDER = ("frame_selection", "missing_lattice")


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
class FrameDrop:
    """The `removed` accounting for a selective-reductive frame reduction (Part 4 §5 removed[0])."""

    path: str
    reason: str
    detail: str


@dataclass
class AppliedAssumption:
    """One recorded recovery decision (Part 4 §2 `Assumption`), plus its field-level effects.

    ``supplied`` is non-empty only for fabricative scenarios; ``removed`` only for selective-
    reductive ones. The two never overlap — the bright line of Part 4 §3.1."""

    id: str
    scenario: str
    choice: str
    parameters: dict[str, Any]
    origin: str  # "preset" | "user". v0.1 is preset-only (D22).
    description: str
    supplied: list[SuppliedField] = field(default_factory=list)
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
                    working, aid, choice, origin
                )
            else:  # missing_lattice
                working, applied = _apply_missing_lattice(
                    working, aid, choice, origin, computed_on_frame=selected_source_index
                )
            assumptions.append(applied)

        return RecoveryResult(canonical=working, assumptions=assumptions, unresolved=[])


def _choice_code(choice: dict[str, Any], scenario: str) -> str:
    code = choice.get("choice")
    if not isinstance(code, str) or code not in available_options(scenario):
        raise RecoveryError(
            f"{scenario!r}: choice {code!r} is not an offered option "
            f"{available_options(scenario)!r}"
        )
    return code


def _apply_frame_selection(
    canonical: CanonicalObject, aid: str, choice: dict[str, Any], origin: str
) -> tuple[CanonicalObject, AppliedAssumption, int]:
    """Reduce a multi-frame object to the single chosen frame (selective reductive, Part 4 §3.1).

    Records an ``Assumption`` and a ``FrameDrop`` (the dropped frames as a `removed` entry) but
    **no** ``SuppliedField`` — the retained frame is genuine source data, not fabricated."""
    code = _choice_code(choice, "frame_selection")
    params = choice.get("parameters", {}) or {}
    n = canonical.frame_count
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


def _apply_missing_lattice(
    canonical: CanonicalObject,
    aid: str,
    choice: dict[str, Any],
    origin: str,
    *,
    computed_on_frame: int,
) -> tuple[CanonicalObject, AppliedAssumption]:
    """Fabricate the target-required lattice the source lacks (fabricative, Part 4 §3.1).

    Writes ``cell.lattice_vectors`` and ``cell.pbc`` into every frame and records an
    ``Assumption`` **and** two ``SuppliedField`` entries — the cell did not exist in the source,
    so it is filed as created, never carried (**P4**). ``pbc`` is set to (T,T,T): POSCAR, the only
    v0.1 lattice-requiring target, is fully periodic by definition (Part 3 §3 n.3)."""
    code = _choice_code(choice, "missing_lattice")
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
