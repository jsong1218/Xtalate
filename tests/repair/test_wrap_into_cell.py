"""wrap-into-cell — the M64 flagship (v1.7 M64-S2; D251).

The version's contract, proven on the one operation with a physics-losing failure mode: an
unwrapped MD trajectory, wrapped on explicit request, converts and validates green, carries
the R5 warning in plain language, and re-derives byte-identically from source + the report's
recorded parameters. Also: the cell-less refusal composes with the existing ``missing_lattice``
recovery (nothing is fabricated), boundary handling is deterministic, and the *transformative*
hazard class is registered and exercised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from tests.conversion.test_engine import _parse, _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.repair import (
    TRANSFORMATIVE_HAZARD,
    RepairRequest,
    apply_repairs,
)
from xtalate.repair.operations import WRAP_DISCARDS_UNWRAPPED_PATHS, WrapIntoCell
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame, Provenance

GOLDEN = Path(__file__).parent.parent / "golden"
XDATCAR = GOLDEN / "xdatcar" / "nacl-md-fixed-cell" / "XDATCAR"


def _convert(
    source: CanonicalObject,
    *,
    reg: Registry | None = None,
    repairs: list[RepairRequest] | None = None,
    **kwargs: Any,
) -> ConversionResult:
    reg = reg or _registry()
    return ConversionEngine(reg).convert(
        source,
        source_format_id="xdatcar",
        target_format_id="xdatcar",
        source_filename="XDATCAR",
        repairs=repairs,
        **kwargs,
    )


def _parsed(reg: Registry) -> CanonicalObject:
    return _parse(reg, "xdatcar", XDATCAR)


def _unwrap(obj: CanonicalObject) -> CanonicalObject:
    """Deterministically push some atoms out of the cell across frames — an unwrapped MD
    trajectory (no RNG; integer lattice translations so wrap must recover the exact originals)."""
    frames: list[Frame] = []
    for i, frame in enumerate(obj.frames):
        assert frame.cell is not None  # the fixture's frames all carry a cell
        lattice = np.asarray(frame.cell.lattice_vectors, dtype=float)
        positions = np.asarray(frame.atoms.positions, dtype=float).copy()
        n = positions.shape[0]
        k = i % 4
        if k == 1:
            positions[0] = positions[0] + lattice[0]
            positions[n // 2] = positions[n // 2] - lattice[1]
        elif k == 2:
            positions[0] = positions[0] + lattice[0] + lattice[1]
            positions[n - 1] = positions[n - 1] - lattice[2]
        elif k == 3:
            positions[0] = positions[0] + 2.0 * lattice[0]
        frames.append(
            frame.model_copy(
                update={"atoms": frame.atoms.model_copy(update={"positions": positions})}
            )
        )
    return obj.model_copy(update={"frames": frames})


# --- the flagship: convert + validate green + R5 warning + reproduce from report ---------


def test_wrap_into_cell_flagship_converts_validates_and_reproduces() -> None:
    reg = _registry()
    parsed = _parsed(reg)
    original_positions = np.asarray(parsed.frames[1].atoms.positions, dtype=float)
    unwrapped = _unwrap(parsed)

    result = _convert(unwrapped, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The repaired object's positions are the original in-cell positions again — the wrap
    # exactly undoes the deterministic unwrapping (allclose: the solve has float noise).
    assert np.allclose(
        np.asarray(result.canonical_out.frames[1].atoms.positions, dtype=float),
        original_positions,
        atol=1e-9,
    )

    # The report's repairs section: one user-requested row with the complete parameters.
    (row,) = result.report.repairs
    assert row.choice == "wrap_into_cell"
    assert row.parameters == {}  # wrap takes no parameters; recorded verbatim (complete)
    assert "minimum-image" in row.description

    # The R5 warning appears in the repairs section (D251: plain language, never glossed).
    assert [w.code for w in result.report.repair_warnings] == ["WRAP_DISCARDS_UNWRAPPED_PATHS"]
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert "diffusion paths" in warning.message

    # Provenance carries the operation="repair" record referencing the same row id.
    history = result.canonical_out.provenance.history
    repair_records = [r for r in history if r.operation == "repair"]
    assert len(repair_records) == 1
    assert repair_records[0].assumptions == [row.id]

    # Reproduce byte-identically from source + the report's recorded parameters alone.
    rederived = _convert(
        unwrapped, reg=reg, repairs=[RepairRequest(row.choice, dict(row.parameters))]
    )
    assert rederived.output is not None and rederived.output == result.output
    assert rederived.validation is not None and rederived.validation.status == "passed"


def test_wrap_is_a_reference_application_within_the_engine() -> None:
    # The same operation applied through apply_repairs (the harness S1 proved) and through the
    # engine lands the same repaired object — one code path, two entry points.
    reg = _registry()
    unwrapped = _unwrap(_parsed(reg))
    outcome = apply_repairs(unwrapped, [RepairRequest("wrap_into_cell")])
    assert outcome.canonical is not None and not outcome.blocked
    assert [a.operation for a in outcome.applied] == ["wrap_into_cell"]
    assert [h.code for h in outcome.applied[0].hazards] == ["WRAP_DISCARDS_UNWRAPPED_PATHS"]

    engine = _convert(unwrapped, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert engine.canonical_out is not None
    for a, b in zip(outcome.canonical.frames, engine.canonical_out.frames, strict=True):
        assert np.array_equal(
            np.asarray(a.atoms.positions, dtype=float),
            np.asarray(b.atoms.positions, dtype=float),
        )


# --- the cell-less refusal composes with missing_lattice; nothing is fabricated -------------


def test_cell_less_wrap_refuses_via_missing_lattice() -> None:
    reg = _registry()
    parsed = _parsed(reg)
    cell_less = parsed.model_copy(
        update={"frames": [f.model_copy(update={"cell": None}) for f in parsed.frames]}
    )

    result = _convert(cell_less, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    assert "wrap_into_cell" in result.report.refusal["message"]
    assert "cell" in result.report.refusal["message"]

    # It resolves through the *existing* scenario, with the pair-specific option list.
    scenarios = result.report.refusal["unresolved_scenarios"]
    assert scenarios and scenarios[0]["scenario"] == "missing_lattice"
    assert scenarios[0]["path"] == "cell.lattice_vectors"
    assert scenarios[0]["options"]  # manual_input/bounding_box — the recovery machinery's own
    assert result.canonical_out is None  # nothing was fabricated, nothing was applied
    assert result.report.repairs == []  # no repair row on a refused-without-application set


def test_degenerate_cell_blocks_too() -> None:
    reg = _registry()
    parsed = _parsed(reg)
    frame = parsed.frames[0]
    degenerate = frame.model_copy(
        update={"cell": Cell(lattice_vectors=np.zeros((3, 3)), pbc=(True, True, True))}
    )
    obj = parsed.model_copy(update={"frames": [degenerate, *parsed.frames[1:]]})

    result = _convert(obj, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    assert "singular" in result.report.refusal["message"]


# --- deterministic boundary handling ------------------------------------------------------


def _cubic(fractional_rows: np.ndarray) -> CanonicalObject:
    lattice = 2.0 * np.eye(3)  # a = b = c = 2 Å, orthogonal — all test coords are exact.
    positions = np.asarray(fractional_rows, dtype=float) @ lattice
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["H", "He", "Li", "Be", "B"][: len(positions)], positions=positions
        ),
        cell=Cell(lattice_vectors=lattice, pbc=(True, True, True)),
    )
    return CanonicalObject(
        frames=[frame],
        provenance=Provenance(
            source_filename="boundary.xyz",
            source_format="extxyz",
            original_coordinate_system="cartesian",
        ),
    )


def test_wrap_boundary_handling_is_deterministic() -> None:
    # Fractional coords on faces/edges and across the origin: 1.0 -> 0.0, 2.25 -> 0.25,
    # -0.5 -> 0.5, -0.25 -> 0.75; 0.5 (exactly mid-face) stays 0.5.
    obj = _cubic(
        np.array(
            [
                [1.0, 0.0, 0.0],
                [0.5, 0.0, 0.0],
                [-0.5, 0.0, 0.0],
                [2.25, 0.0, 0.0],
                [-0.25, 0.0, 0.0],
            ]
        )
    )
    outcome = apply_repairs(obj, [RepairRequest("wrap_into_cell")])
    assert outcome.canonical is not None and not outcome.blocked
    wrapped = np.asarray(outcome.canonical.frames[0].atoms.positions, dtype=float)
    expected = np.array(
        [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [0.5, 0.0, 0.0], [0.25, 0.0, 0.0], [0.75, 0.0, 0.0]]
    ) @ (2.0 * np.eye(3))
    assert np.array_equal(wrapped, expected)

    # The same input lands the same output on every run — and the engine path agrees.
    again = apply_repairs(obj, [RepairRequest("wrap_into_cell")])
    assert again.canonical is not None
    assert np.array_equal(
        np.asarray(again.canonical.frames[0].atoms.positions, dtype=float), wrapped
    )
    reg = _registry()
    converted = _convert(obj, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert converted.canonical_out is not None
    assert np.array_equal(
        np.asarray(converted.canonical_out.frames[0].atoms.positions, dtype=float), wrapped
    )


# --- the transformative hazard class (D251) ------------------------------------------------


def test_transformative_hazard_class_is_registered_and_exercised() -> None:
    # The class exists, wrap declares it, and it is not a recovery scenario — repairs are not
    # recovery scenarios (the class is a repair-side declaration, Part 4 §3.1's fourth class).
    assert TRANSFORMATIVE_HAZARD == "transformative"
    assert WrapIntoCell.hazard_class == TRANSFORMATIVE_HAZARD
    assert WrapIntoCell.hazards == (WRAP_DISCARDS_UNWRAPPED_PATHS,)
    assert WRAP_DISCARDS_UNWRAPPED_PATHS.code == "WRAP_DISCARDS_UNWRAPPED_PATHS"

    # Exercised end to end: the warning row is source="repair" with the R5 text verbatim.
    reg = _registry()
    result = _convert(_unwrap(_parsed(reg)), reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert warning.code == WRAP_DISCARDS_UNWRAPPED_PATHS.code
    assert warning.message == WRAP_DISCARDS_UNWRAPPED_PATHS.message
