"""Partial ``missing_lattice`` fabrication over a `mixed` cell (M13).

The case a *multi-frame lattice-requiring target* makes reachable for the first time. Until
XDATCAR, every target that required ``cell.lattice_vectors`` (POSCAR, CONTCAR) capped at
``max_frames=1``, so ``frame_selection`` always reduced a ``mixed`` cell to one frame before
``missing_lattice`` ran: the lattice was then wholly genuine or wholly fabricated, never both.
XDATCAR requires a lattice *and* keeps every frame, so a source whose cell is present in some
frames and absent in others ends with both outcomes at once.

The report must state both — ``preserved`` for the frames that carried a real lattice,
``supplied`` for the frames that were given one. Claiming only ``supplied`` would deny that
genuine lattices were carried; claiming only ``preserved`` would hide a fabrication (P1, P4).
Found by the M10 hypothesis property test the moment XDATCAR registered.
"""

from __future__ import annotations

import numpy as np

from xtalate.conversion import ConversionEngine
from xtalate.conversion.engine import ConversionResult
from xtalate.registry import default_registry
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    Provenance,
    TrajectoryMetadata,
)

_REGISTRY = default_registry()
_BOX = {"choice": "bounding_box", "parameters": {"padding_ang": 2.0}}


def _mixed_cell_source() -> CanonicalObject:
    """Frame 0 has no cell; frame 1 carries a real one — ``cell.lattice_vectors`` is `mixed`."""
    positions = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    return CanonicalObject(
        frames=[
            Frame(index=0, atoms=AtomsBlock(symbols=["H", "H"], positions=positions), cell=None),
            Frame(
                index=1,
                atoms=AtomsBlock(symbols=["H", "H"], positions=positions),
                cell=Cell(lattice_vectors=np.eye(3) * 9.0, pbc=(True, True, True)),
            ),
        ],
        trajectory=TrajectoryMetadata(timestep=None),
        provenance=Provenance(
            source_filename=None, source_format="extxyz", original_coordinate_system="cartesian"
        ),
    )


def _convert() -> ConversionResult:
    return ConversionEngine(_REGISTRY).convert(
        _mixed_cell_source(),
        source_format_id="extxyz",
        target_format_id="xdatcar",
        mode="permissive",
        recovery_choices={"missing_lattice": _BOX},
    )


def test_source_cell_is_actually_mixed() -> None:
    presence = _mixed_cell_source().field_presence()
    assert presence.status_of("cell.lattice_vectors") == "mixed"


def test_conversion_completes() -> None:
    assert _convert().report.status == "completed"


def test_lattice_is_reported_both_preserved_and_supplied() -> None:
    """The heart of it: one path, two honest outcomes across frames."""
    report = _convert().report
    assert "cell.lattice_vectors" in {e.path for e in report.preserved}
    assert "cell.lattice_vectors" in {e.path for e in report.supplied}


def test_the_report_names_which_frames_got_which() -> None:
    """A path-level report is coarse, so the detail text has to carry the frame-level truth —
    otherwise "preserved and supplied" is unreadable rather than precise."""
    report = _convert().report
    preserved = next(e for e in report.preserved if e.path == "cell.lattice_vectors")
    supplied = next(e for e in report.supplied if e.path == "cell.lattice_vectors")
    assert "[1]" in (preserved.detail or "")  # frame 1 carried its own lattice
    assert "[0]" in (supplied.detail or "")  # frame 0 was given one


def test_the_genuine_lattice_is_not_overwritten() -> None:
    """P4 in the data, not just the report: the frame that had a real cell keeps it exactly."""
    out = _convert()
    assert out.canonical_out is not None
    frame1 = out.canonical_out.frames[1]
    assert frame1.cell is not None
    np.testing.assert_allclose(frame1.cell.lattice_vectors, np.eye(3) * 9.0)


def test_the_fabricated_lattice_traces_to_an_assumption() -> None:
    report = _convert().report
    supplied = next(e for e in report.supplied if e.path == "cell.lattice_vectors")
    assumption = next(a for a in report.assumptions if a.id == supplied.from_assumption)
    assert assumption.scenario == "missing_lattice"
    assert assumption.choice == "bounding_box"


def test_a_uniformly_present_lattice_is_never_supplied() -> None:
    """The other side of the boundary: when every frame already has a cell, `missing_lattice`
    must not fire at all. This is what the completeness invariant still catches unconditionally
    — supplying a field every frame has can only be overwrite of genuine data."""
    source = _mixed_cell_source()
    source.frames[0].cell = Cell(lattice_vectors=np.eye(3) * 9.0, pbc=(True, True, True))
    result = ConversionEngine(_REGISTRY).convert(
        source,
        source_format_id="extxyz",
        target_format_id="xdatcar",
        mode="permissive",
        recovery_choices={"missing_lattice": _BOX},
    )
    assert "cell.lattice_vectors" not in {e.path for e in result.report.supplied}
    assert "cell.lattice_vectors" in {e.path for e in result.report.preserved}


def test_relative_motion_between_frames_survives_the_shared_bounding_box() -> None:
    """The box is built on one frame and applied to every cell-less frame with a *single* rigid
    shift. Per-frame boxes would silently re-centre each frame and destroy the displacement
    information that is the whole point of a trajectory."""
    source = _mixed_cell_source()
    source.frames[1].cell = None  # both frames cell-less, and frame 1 displaced from frame 0
    source.frames[1].atoms.positions = source.frames[1].atoms.positions + 3.0
    result = ConversionEngine(_REGISTRY).convert(
        source,
        source_format_id="extxyz",
        target_format_id="xdatcar",
        mode="permissive",
        recovery_choices={"missing_lattice": _BOX},
    )
    assert result.canonical_out is not None
    before = source.frames[1].atoms.positions - source.frames[0].atoms.positions
    after = (
        result.canonical_out.frames[1].atoms.positions
        - result.canonical_out.frames[0].atoms.positions
    )
    np.testing.assert_allclose(before, after)
