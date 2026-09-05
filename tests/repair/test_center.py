"""center — the transformative translate (v1.7 M65-S2; D253).

``center`` moves a stated reference point of the structure to a stated target, per
frame, positions only. Tests: the flagship (convert + validate green + the
``CENTER_DISCARDS_ABSOLUTE_POSITION`` warning + byte-identical re-derivation from
source + recorded parameters), all four reference/target combinations (centroid→origin,
centroid→cell_center, cell_center→origin, explicit-coordinate target), the cell-less
refusal through ``missing_lattice`` (nothing fabricated), positions-only (velocities/
forces/charges provably untouched), per-frame independence on a trajectory, and the
two no-default ``RepairError`` refusals.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tests.conversion.test_engine import _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.repair import (
    TRANSFORMATIVE_HAZARD,
    RepairRequest,
    apply_repairs,
    get_operation,
)
from xtalate.repair.operations import (
    CENTER_DISCARDS_ABSOLUTE_POSITION,
    Center,
)
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    Provenance,
)


def _provenance(filename: str = "source.vasp") -> Provenance:
    return Provenance(
        source_filename=filename,
        source_format="poscar",
        original_coordinate_system="cartesian",
    )


def _single() -> CanonicalObject:
    """A single frame whose geometric centroid is exactly [1, 1, 0] Å, with velocities,
    forces, and charges present so the positions-only test can prove they are untouched."""
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["Na", "Cl", "Na", "Cl"],
            positions=np.array(
                [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [2.0, 2.0, 0.0]],
                dtype=float,
            ),
        ),
        cell=Cell(lattice_vectors=6.0 * np.eye(3), pbc=(True, True, True)),
        dynamics=Dynamics(
            velocities=np.array(
                [[0.1, 0.0, 0.0], [0.0, 0.2, 0.0], [0.0, 0.0, 0.3], [0.4, 0.4, 0.4]],
                dtype=float,
            ),
            forces=np.array(
                [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0], [4.0, 0.0, 0.0]],
                dtype=float,
            ),
        ),
        electronic=Electronic(charges=np.array([-1.0, 1.0, -1.0, 1.0])),
    )
    return CanonicalObject(frames=[frame], provenance=_provenance())


def _trajectory() -> CanonicalObject:
    """Three frames with distinct centroids — each frame must be centered by its own
    reference point, not by frame 0's (per-frame independence)."""
    frames: list[Frame] = []
    for i in range(3):
        frames.append(
            Frame(
                index=i,
                atoms=AtomsBlock(
                    symbols=["H", "O", "H"],
                    positions=np.array(
                        [
                            [0.0 + i, 0.0, 0.0],
                            [1.0, 1.0 + i, 0.0],
                            [2.0, 0.0, 1.0],
                        ],
                        dtype=float,
                    ),
                ),
                cell=Cell(lattice_vectors=5.0 * np.eye(3), pbc=(True, True, True)),
            )
        )
    return CanonicalObject(frames=frames, provenance=_provenance("traj.vasp"))


def _apply(obj: CanonicalObject, parameters: dict[str, Any]) -> tuple[CanonicalObject, Any]:
    outcome = apply_repairs(obj, [RepairRequest("center", parameters)])
    assert outcome.canonical is not None and not outcome.blocked
    assert [a.operation for a in outcome.applied] == ["center"]
    return outcome.canonical, outcome.applied[0]


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
        source_format_id="poscar",
        target_format_id="poscar",
        source_filename="source.vasp",
        repairs=repairs,
        **kwargs,
    )


# --- registration + the transformative posture --------------------------------------------


def test_center_is_registered_and_transformative() -> None:
    op = get_operation("center")
    assert isinstance(op, Center)
    assert op.operation == "center"
    assert op.hazard_class == TRANSFORMATIVE_HAZARD
    assert op.hazards == (CENTER_DISCARDS_ABSOLUTE_POSITION,)
    assert CENTER_DISCARDS_ABSOLUTE_POSITION.code == "CENTER_DISCARDS_ABSOLUTE_POSITION"
    assert "not recoverable" in CENTER_DISCARDS_ABSOLUTE_POSITION.message
    assert "relative geometry is preserved" in CENTER_DISCARDS_ABSOLUTE_POSITION.message


# --- all four reference/target combinations -----------------------------------------------


def test_centroid_to_origin() -> None:
    source = _single()
    repaired, record = _apply(source, {"reference": "centroid", "target": "origin"})
    positions = np.asarray(repaired.frames[0].atoms.positions)
    # The centroid lands exactly on the origin: mean of the shifted positions is [0, 0, 0].
    assert np.allclose(positions.mean(axis=0), [0.0, 0.0, 0.0], atol=1e-12)
    expected = np.asarray(source.frames[0].atoms.positions) - np.array([1.0, 1.0, 0.0])
    assert np.array_equal(positions, expected)
    assert record.parameters == {"reference": "centroid", "target": "origin"}
    assert "translated the centroid to origin" in record.description


def test_centroid_to_cell_center() -> None:
    source = _single()
    repaired, _ = _apply(source, {"reference": "centroid", "target": "cell_center"})
    # cell_center of the 6 Å cubic cell is [3, 3, 3]; the centroid lands exactly there.
    assert np.allclose(
        np.asarray(repaired.frames[0].atoms.positions).mean(axis=0), [3.0, 3.0, 3.0], atol=1e-12
    )


def test_cell_center_to_origin() -> None:
    source = _single()
    repaired, _ = _apply(source, {"reference": "cell_center", "target": "origin"})
    # Shift is -[3, 3, 3]: the frame's cell center lands on the origin.
    expected = np.asarray(source.frames[0].atoms.positions) - np.array([3.0, 3.0, 3.0])
    assert np.array_equal(np.asarray(repaired.frames[0].atoms.positions), expected)


def test_explicit_coordinate_target() -> None:
    source = _single()
    repaired, _ = _apply(source, {"reference": "centroid", "target": [1.0, 2.0, 3.0]})
    assert np.allclose(
        np.asarray(repaired.frames[0].atoms.positions).mean(axis=0), [1.0, 2.0, 3.0], atol=1e-12
    )


# --- positions only: velocities/forces/charges are translation-invariant ------------------


def test_center_touches_positions_only() -> None:
    source = _single()
    repaired, _ = _apply(source, {"reference": "centroid", "target": "origin"})
    assert not np.array_equal(
        np.asarray(repaired.frames[0].atoms.positions),
        np.asarray(source.frames[0].atoms.positions),
    )
    assert repaired.frames[0].dynamics.velocities is not None
    assert source.frames[0].dynamics.velocities is not None
    assert np.array_equal(
        repaired.frames[0].dynamics.velocities, source.frames[0].dynamics.velocities
    )
    assert repaired.frames[0].dynamics.forces is not None
    assert source.frames[0].dynamics.forces is not None
    assert np.array_equal(repaired.frames[0].dynamics.forces, source.frames[0].dynamics.forces)
    assert repaired.frames[0].electronic.charges is not None
    assert source.frames[0].electronic.charges is not None
    assert np.array_equal(
        repaired.frames[0].electronic.charges, source.frames[0].electronic.charges
    )


# --- per-frame independence on a trajectory -----------------------------------------------


def test_center_centers_each_frame_by_its_own_reference() -> None:
    source = _trajectory()
    repaired, _ = _apply(source, {"reference": "centroid", "target": "origin"})
    for frame in repaired.frames:
        assert np.allclose(
            np.asarray(frame.atoms.positions).mean(axis=0), [0.0, 0.0, 0.0], atol=1e-12
        )
    # And each frame's shift is its own centroid, not frame 0's.
    for out, src in zip(repaired.frames, source.frames, strict=True):
        expected = np.asarray(src.atoms.positions) - np.asarray(src.atoms.positions).mean(axis=0)
        assert np.array_equal(np.asarray(out.atoms.positions), expected)


# --- the cell-less refusal composes with missing_lattice; nothing is fabricated ------------


def test_cell_less_cell_center_refuses_via_missing_lattice() -> None:
    reg = _registry()
    source = _single().model_copy(
        update={"frames": [_single().frames[0].model_copy(update={"cell": None})]}
    )
    for parameters in (
        {"reference": "cell_center", "target": "origin"},
        {"reference": "centroid", "target": "cell_center"},
    ):
        result = _convert(source, reg=reg, repairs=[RepairRequest("center", parameters)])
        assert result.report.status == "refused"
        assert result.report.refusal is not None
        assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
        assert "cell" in result.report.refusal["message"]
        scenarios = result.report.refusal["unresolved_scenarios"]
        assert scenarios and scenarios[0]["scenario"] == "missing_lattice"
        assert scenarios[0]["path"] == "cell.lattice_vectors"
        assert scenarios[0]["options"]  # manual_input/bounding_box — recovery's own options
        assert result.canonical_out is None  # nothing fabricated, nothing applied
        assert result.report.repairs == []


def test_centroid_to_origin_needs_no_cell() -> None:
    source = _single().model_copy(
        update={"frames": [_single().frames[0].model_copy(update={"cell": None})]}
    )
    repaired, _ = _apply(source, {"reference": "centroid", "target": "origin"})
    assert np.allclose(
        np.asarray(repaired.frames[0].atoms.positions).mean(axis=0), [0.0, 0.0, 0.0], atol=1e-12
    )


def test_degenerate_cell_blocks_too() -> None:
    reg = _registry()
    degenerate = (
        _single()
        .frames[0]
        .model_copy(update={"cell": Cell(lattice_vectors=np.zeros((3, 3)), pbc=(True, True, True))})
    )
    source = _single().model_copy(update={"frames": [degenerate]})
    result = _convert(
        source,
        reg=reg,
        repairs=[RepairRequest("center", {"reference": "cell_center", "target": "origin"})],
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert "singular" in result.report.refusal["message"]


# --- the two no-default RepairErrors ------------------------------------------------------


def test_center_requires_reference_and_target() -> None:
    source = _single()
    for parameters in (
        {"target": "origin"},  # missing reference
        {"reference": "centroid"},  # missing target
        {"reference": None, "target": "origin"},
        {"reference": "centroid", "target": None},
        {"reference": "bogus", "target": "origin"},
        {"reference": "centroid", "target": "bogus"},
        {"reference": "centroid", "target": [1.0, 2.0]},  # not a 3-vector
        {"reference": "centroid", "target": [1.0, 2.0, "x"]},  # not numeric
    ):
        try:
            apply_repairs(source, [RepairRequest("center", parameters)])
        except ValueError as exc:
            assert "reference" in str(exc) or "target" in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"center must refuse parameters {parameters!r}")


# --- flagship: convert + validate green + warning + reproduce byte-identically -------------


def test_center_flagship_converts_validates_and_reproduces() -> None:
    reg = _registry()
    source = _single()

    result = _convert(
        source,
        reg=reg,
        repairs=[RepairRequest("center", {"reference": "centroid", "target": "origin"})],
    )
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The report's repairs section: one row with the complete recorded parameters.
    (row,) = result.report.repairs
    assert row.choice == "center"
    assert row.parameters == {"reference": "centroid", "target": "origin"}
    assert "Centered the structure" in row.description

    # The transformative warning appears, source="repair" (D251: plain language, never glossed).
    assert [w.code for w in result.report.repair_warnings] == ["CENTER_DISCARDS_ABSOLUTE_POSITION"]
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert "not recoverable from the centered file" in warning.message

    # Provenance carries the operation="repair" record referencing the same row id.
    repair_records = [r for r in result.canonical_out.provenance.history if r.operation == "repair"]
    assert len(repair_records) == 1
    assert repair_records[0].assumptions == [row.id]

    # Reproduce byte-identically from source + the report's recorded parameters alone.
    rederived = _convert(source, reg=reg, repairs=[RepairRequest(row.choice, dict(row.parameters))])
    assert rederived.output is not None and rederived.output == result.output
    assert rederived.validation is not None and rederived.validation.status == "passed"
