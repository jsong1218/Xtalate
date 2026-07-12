"""field_presence() / PresenceMap trichotomy and granularity rules (Part 2 §3.11)."""

from __future__ import annotations

import numpy as np

from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    Provenance,
    SimulationMetadata,
    UserMetadata,
)


def _atoms(n: int = 2) -> AtomsBlock:
    return AtomsBlock(
        symbols=["O"] + ["H"] * (n - 1),
        positions=np.array([[float(i), 0.0, 0.0] for i in range(n)]),
    )


def _provenance() -> Provenance:
    return Provenance(
        source_filename="t.xyz", source_format="xyz", original_coordinate_system="cartesian"
    )


def test_plain_xyz_presence_matches_discovery_example() -> None:
    # The §8.1 worked example: ✓ Species, ✓ positions, ✗ Lattice/Velocities/Forces/Energies,
    # ✓ Comments (carried in custom_per_frame).
    obj = CanonicalObject(
        frames=[Frame(index=0, atoms=_atoms(3)), Frame(index=1, atoms=_atoms(3))],
        trajectory=None,
        provenance=_provenance(),
        user_metadata=UserMetadata(custom_per_frame={"xyz:comment": np.array([0.0, 1.0])}),
    )
    pm = obj.field_presence()
    assert pm.schema_version == "0.1.0"
    assert pm.status_of("atoms.symbols") == "present"
    assert pm.status_of("atoms.positions") == "present"
    assert pm.status_of("cell.lattice_vectors") == "absent"
    assert pm.status_of("dynamics.velocities") == "absent"
    assert pm.status_of("dynamics.forces") == "absent"
    assert pm.status_of("electronic.total_energy") == "absent"
    assert "user_metadata.custom_per_frame['xyz:comment']" in pm.present_paths()


def test_root_field_never_mixed_and_reads_present() -> None:
    obj = CanonicalObject(
        frames=[Frame(index=0, atoms=_atoms())],
        simulation=SimulationMetadata(xc_functional="PBE"),
        provenance=_provenance(),
    )
    pm = obj.field_presence()
    assert pm.status_of("simulation.xc_functional") == "present"
    assert pm.status_of("simulation.calculator") == "absent"
    # empty container is absent
    assert pm.status_of("simulation.extra") == "absent"
    assert pm.status_of("user_metadata.tags") == "absent"


def test_per_frame_field_present_in_all_frames_is_present() -> None:
    frames = [
        Frame(index=0, atoms=_atoms(), electronic=Electronic(total_energy=-1.0)),
        Frame(index=1, atoms=_atoms(), electronic=Electronic(total_energy=-1.1)),
    ]
    obj = CanonicalObject(frames=frames, provenance=_provenance())
    entry = next(e for e in obj.field_presence().entries if e.path == "electronic.total_energy")
    assert entry.status == "present"
    assert entry.present_frames is None


def test_per_frame_field_present_in_some_frames_is_mixed() -> None:
    # Energy in frame 0 only -> mixed, with present_frames listing the index.
    frames = [
        Frame(index=0, atoms=_atoms(), electronic=Electronic(total_energy=-1.0)),
        Frame(index=1, atoms=_atoms(), electronic=Electronic()),
        Frame(index=2, atoms=_atoms(), electronic=Electronic(total_energy=-1.2)),
    ]
    obj = CanonicalObject(frames=frames, provenance=_provenance())
    pm = obj.field_presence()
    entry = next(e for e in pm.entries if e.path == "electronic.total_energy")
    assert entry.status == "mixed"
    assert entry.present_frames == [0, 2]
    assert "electronic.total_energy" in pm.present_paths()


def test_zero_value_counts_as_present() -> None:
    # velocities of all zeros = "source states at rest", present not absent (§2 rule 3).
    frame = Frame(index=0, atoms=_atoms(), dynamics=Dynamics(velocities=np.zeros((2, 3))))
    obj = CanonicalObject(frames=[frame], provenance=_provenance())
    assert obj.field_presence().status_of("dynamics.velocities") == "present"


def test_empty_constraints_list_is_present() -> None:
    # [] = explicitly declared "no constraints" — information, not absence (§3.6).
    frame = Frame(index=0, atoms=_atoms(), dynamics=Dynamics(constraints=[]))
    obj = CanonicalObject(frames=[frame], provenance=_provenance())
    assert obj.field_presence().status_of("dynamics.constraints") == "present"


def test_cell_present_when_declared() -> None:
    cell = Cell(lattice_vectors=np.eye(3) * 5.64, pbc=(True, True, True))
    obj = CanonicalObject(
        frames=[Frame(index=0, atoms=_atoms(), cell=cell)], provenance=_provenance()
    )
    pm = obj.field_presence()
    assert pm.status_of("cell.lattice_vectors") == "present"
    assert pm.status_of("cell.pbc") == "present"
    assert pm.status_of("cell.space_group") == "absent"  # POSCAR declares none
