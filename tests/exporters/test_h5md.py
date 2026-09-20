"""H5MD exporter tests (v2.0 M74).

S1 pins the exporter's variable-N write mechanism against a round-trip fixture: a genuine
grand-canonical trajectory (frame 0 has 2 atoms, frame 1 has 3) must survive
export → re-parse within tolerance, proving the M72/M73 variable-N engines on a real binary
container before any of the richer field mapping is built (the go/no-go).
"""

from __future__ import annotations

from io import BytesIO

import h5py
import numpy as np
import pytest

from xtalate.exporters.h5md import H5MDExporter
from xtalate.parsers.h5md import H5MDParser
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    Provenance,
    TrajectoryMetadata,
    UserMetadata,
)


def _variable_n_object() -> CanonicalObject:
    # Grand-canonical: frame 0 has 2 atoms, frame 1 has 3 (a real variable-N trajectory).
    cell = Cell(
        lattice_vectors=np.array([[10.0, 0, 0], [0, 10, 0], [0, 0, 10]]), pbc=(True, True, True)
    )
    f0 = Frame(
        index=0,
        atoms=AtomsBlock(symbols=["H", "O"], positions=np.array([[0.0, 0, 0], [0, 0, 1.0]])),
        cell=cell,
    )
    f1 = Frame(
        index=1,
        atoms=AtomsBlock(
            symbols=["H", "O", "H"],
            positions=np.array([[0.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]]),
        ),
        cell=cell,
    )
    provenance = Provenance(
        source_filename=None,
        source_format="h5md",
        original_coordinate_system="cartesian",
    )
    return CanonicalObject(
        frames=[f0, f1], trajectory=TrajectoryMetadata(timestep=None), provenance=provenance
    )


def test_variable_n_h5md_round_trips_within_tolerance() -> None:
    src = _variable_n_object()
    buf = BytesIO()
    H5MDExporter().export(src, buf)
    buf.seek(0)
    result = H5MDParser().parse(buf, filename="rt.h5")
    obj = result.canonical
    assert [len(fr.atoms.atomic_numbers) for fr in obj.frames] == [2, 3]
    np.testing.assert_allclose(
        obj.frames[1].atoms.positions,
        np.array([[0.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]]),
        atol=1e-8,
    )
    assert obj.frames[0].atoms.atomic_numbers == [1, 8]
    assert obj.frames[1].atoms.atomic_numbers == [1, 8, 1]


def _rich_object() -> CanonicalObject:
    """A constant-N object exercising every mapped field: velocities, forces, masses, charges, a
    per-frame total energy, an ``h5md:temperature`` per-frame observable, and a cell that *varies*
    between the two frames (so the exporter must write a time-dependent box)."""
    f0 = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["H", "O"],
            positions=np.array([[0.0, 0, 0], [0, 0, 1.0]]),
            masses=np.array([1.008, 15.999]),
        ),
        cell=Cell(lattice_vectors=np.diag([10.0, 10.0, 10.0]), pbc=(True, True, True)),
        dynamics=Dynamics(
            velocities=np.array([[0.1, 0.0, 0.0], [0.0, 0.2, 0.0]]),
            forces=np.array([[0.0, 0.0, -1.0], [0.0, 0.0, 1.0]]),
        ),
        electronic=Electronic(total_energy=-12.5, charges=np.array([0.4, -0.4])),
    )
    f1 = Frame(
        index=1,
        atoms=AtomsBlock(
            symbols=["H", "O"],
            positions=np.array([[0.0, 0, 0], [0, 0, 1.1]]),
            masses=np.array([1.008, 15.999]),
        ),
        cell=Cell(lattice_vectors=np.diag([11.0, 11.0, 11.0]), pbc=(True, True, True)),
        dynamics=Dynamics(
            velocities=np.array([[0.15, 0.0, 0.0], [0.0, 0.25, 0.0]]),
            forces=np.array([[0.0, 0.0, -0.9], [0.0, 0.0, 0.9]]),
        ),
        electronic=Electronic(total_energy=-12.6, charges=np.array([0.5, -0.5])),
    )
    provenance = Provenance(
        source_filename=None, source_format="h5md", original_coordinate_system="cartesian"
    )
    return CanonicalObject(
        frames=[f0, f1],
        trajectory=TrajectoryMetadata(timestep=None),
        provenance=provenance,
        user_metadata=UserMetadata(custom_per_frame={"h5md:temperature": np.array([300.0, 305.0])}),
    )


def test_every_mapped_field_round_trips() -> None:
    src = _rich_object()
    buf = BytesIO()
    H5MDExporter().export(src, buf)
    buf.seek(0)
    obj = H5MDParser().parse(buf, filename="rich.h5").canonical

    v1 = obj.frames[1].dynamics.velocities
    force0 = obj.frames[0].dynamics.forces
    masses0 = obj.frames[0].atoms.masses
    charges1 = obj.frames[1].electronic.charges
    assert v1 is not None and force0 is not None and masses0 is not None and charges1 is not None
    np.testing.assert_allclose(v1, [[0.15, 0.0, 0.0], [0.0, 0.25, 0.0]], atol=1e-8)
    np.testing.assert_allclose(force0, [[0.0, 0.0, -1.0], [0.0, 0.0, 1.0]], atol=1e-8)
    np.testing.assert_allclose(masses0, [1.008, 15.999], atol=1e-8)
    np.testing.assert_allclose(charges1, [0.5, -0.5], atol=1e-8)
    assert obj.frames[0].electronic.total_energy == pytest.approx(-12.5)
    assert obj.frames[1].electronic.total_energy == pytest.approx(-12.6)
    np.testing.assert_allclose(
        np.asarray(obj.user_metadata.custom_per_frame["h5md:temperature"]), [300.0, 305.0]
    )


def test_time_dependent_box_survives_a_per_frame_varying_cell() -> None:
    src = _rich_object()  # cell diag 10 on frame 0, diag 11 on frame 1
    buf = BytesIO()
    H5MDExporter().export(src, buf)
    buf.seek(0)
    obj = H5MDParser().parse(buf, filename="box.h5").canonical
    c0, c1 = obj.frames[0].cell, obj.frames[1].cell
    assert c0 is not None and c1 is not None
    np.testing.assert_allclose(np.diag(c0.lattice_vectors), [10.0, 10.0, 10.0])
    np.testing.assert_allclose(np.diag(c1.lattice_vectors), [11.0, 11.0, 11.0])


def test_canonical_unit_attributes_are_written() -> None:
    src = _rich_object()
    buf = BytesIO()
    H5MDExporter().export(src, buf)
    buf.seek(0)
    with h5py.File(buf, "r") as f:
        assert f["particles/all/position/value"].attrs["unit"] == "Angstrom"
        assert f["particles/all/velocity/value"].attrs["unit"] == "Angstrom/fs"
        assert f["particles/all/force/value"].attrs["unit"] == "eV/Angstrom"
        assert f["particles/all/mass/value"].attrs["unit"] == "u"
        assert f["particles/all/charge/value"].attrs["unit"] == "e"
        assert f["observables/potential_energy/value"].attrs["unit"] == "eV"


def test_h5md_applies_no_transformation_so_export_warnings_is_empty() -> None:
    # H5MD's canonical spelling is Xtalate's, so nothing is converted or sign-flipped (P1).
    assert H5MDExporter().export_warnings(_rich_object()) == []


def test_a_field_present_on_only_some_frames_is_unrepresentable() -> None:
    src = _rich_object()
    # Strip the velocities from frame 1 only — a mixed field the per-step layout cannot express.
    src.frames[1].dynamics = Dynamics(velocities=None, forces=src.frames[1].dynamics.forces)
    reason = H5MDExporter().unrepresentable(src)
    assert reason is not None
    assert "velocities" in reason


def test_a_representable_object_has_no_unrepresentable_reason() -> None:
    assert H5MDExporter().unrepresentable(_rich_object()) is None
