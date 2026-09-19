"""Variable-N pre-flight refusal (v2.0 M73-S3, D276; Part 4 §3.3).

Schema 2.0.0 allows a source whose frames differ in atom count. Against a constant-N target
(``supports_variable_atom_count=False`` — POSCAR/CONTCAR/XDATCAR) the format cannot express the
varying composition, so the pre-flight refuses with the **same** ``frame_selection`` recovery the
frame-cap uses: pick one frame (a single fixed-N structure) or split per frame. It is never
padded, masked, or truncated to one N — ghost atoms are a silent fabrication (P1). The trigger is
keyed on the target's declared capability, read straight from the declaration, not a hard-coded
format list (P6).

These build the variable-N object in memory: the extXYZ/dump/ase_traj readers still refuse a
variable-N file at parse time until M73-S4 retires that constant-N reader refusal, so a parser
cannot yet produce one. S4 adds the read-through cases; S3 proves the pre-flight axis alone.
"""

from __future__ import annotations

import numpy as np

from xtalate.conversion import ConversionEngine
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
_ENGINE = ConversionEngine(_REGISTRY)
_LATTICE = np.eye(3) * 6.0


def _variable_n_source() -> CanonicalObject:
    """Frame 0 has three atoms, frame 1 has two — a variable-N trajectory (both frames carry a
    real cell so ``missing_lattice`` never confounds the variable-N trigger)."""
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=["O", "H", "H"], positions=np.zeros((3, 3), dtype=float)),
                cell=Cell(lattice_vectors=_LATTICE, pbc=(True, True, True)),
            ),
            Frame(
                index=1,
                atoms=AtomsBlock(symbols=["O", "H"], positions=np.zeros((2, 3), dtype=float)),
                cell=Cell(lattice_vectors=_LATTICE, pbc=(True, True, True)),
            ),
        ],
        trajectory=TrajectoryMetadata(timestep=None),
        provenance=Provenance(
            source_filename=None, source_format="extxyz", original_coordinate_system="cartesian"
        ),
    )


def _constant_n_source() -> CanonicalObject:
    """Two frames, both three atoms — constant N; a POSCAR target reduces on frame_selection but
    never on the variable-N axis."""
    return CanonicalObject(
        frames=[
            Frame(
                index=i,
                atoms=AtomsBlock(symbols=["O", "H", "H"], positions=np.zeros((3, 3), dtype=float)),
                cell=Cell(lattice_vectors=_LATTICE, pbc=(True, True, True)),
            )
            for i in range(2)
        ],
        trajectory=TrajectoryMetadata(timestep=None),
        provenance=Provenance(
            source_filename=None, source_format="extxyz", original_coordinate_system="cartesian"
        ),
    )


def test_variable_n_source_to_poscar_refuses_at_preflight_with_frame_selection() -> None:
    result = _ENGINE.convert(
        _variable_n_source(), source_format_id="extxyz", target_format_id="poscar"
    )
    assert result.report.status == "refused"
    assert result.output is None
    assert result.report.refusal is not None
    scenarios = result.report.refusal["unresolved_scenarios"]
    assert any(s["scenario"] == "frame_selection" for s in scenarios)
    detail = next(s for s in scenarios if s["scenario"] == "frame_selection")["detail"]
    assert "differ in atom count" in detail


def test_variable_n_to_xdatcar_refuses_even_though_xdatcar_keeps_frames() -> None:
    # XDATCAR has no max_frames cap (it keeps every frame) but writes one shared header count, so
    # it is constant-N: the variable-N axis is what refuses here, not the frame cap.
    result = _ENGINE.convert(
        _variable_n_source(), source_format_id="extxyz", target_format_id="xdatcar"
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    scenarios = result.report.refusal["unresolved_scenarios"]
    assert any(s["scenario"] == "frame_selection" for s in scenarios)


def test_no_ghost_atoms_ever_fabricated() -> None:
    # The refusal path produces no output at all — nothing is padded, masked, or truncated to a
    # single N to force a fixed-composition write (P1). A permissive mode does not change that:
    # a constant-N target cannot hold variable N, so it refuses rather than inventing atoms.
    result = _ENGINE.convert(
        _variable_n_source(),
        source_format_id="extxyz",
        target_format_id="poscar",
        mode="permissive",
    )
    assert result.report.status == "refused"
    assert result.output is None
    assert result.canonical_out is None


def test_variable_n_to_extxyz_is_not_refused_on_the_axis() -> None:
    # extXYZ holds variable N (a fresh count line per frame), so the axis never fires; the
    # conversion is not refused for atom-count divergence.
    result = _ENGINE.convert(
        _variable_n_source(), source_format_id="extxyz", target_format_id="extxyz"
    )
    if result.report.status == "refused":
        assert result.report.refusal is not None
        scenarios = result.report.refusal["unresolved_scenarios"]
        assert all("differ in atom count" not in s.get("detail", "") for s in scenarios)


def test_constant_n_source_to_poscar_does_not_fire_the_variable_n_axis() -> None:
    # A constant-N multi-frame source to POSCAR still reduces on the frame cap, but the detail is
    # the frame-count wording, never the variable-N wording — the two triggers stay distinct.
    result = _ENGINE.convert(
        _constant_n_source(), source_format_id="extxyz", target_format_id="poscar"
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    scenarios = result.report.refusal["unresolved_scenarios"]
    fs = next(s for s in scenarios if s["scenario"] == "frame_selection")
    assert "differ in atom count" not in fs["detail"]
    assert "target holds at most" in fs["detail"]
