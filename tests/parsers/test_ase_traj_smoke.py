"""M14A smoke tests: the ase_traj parser/exporter register, declare capabilities, and round-trip
in memory (Part 3 §3). The exhaustive default-laundering suite is M14B (test_ase_traj.py); this
module proves the spine end to end.
"""

from __future__ import annotations

import io

import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixAtoms
from ase.io.trajectory import TrajectoryWriter

from xtalate.exporters.ase_traj import make_ase_traj_exporter
from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.exporters.poscar import make_poscar_exporter
from xtalate.parsers.ase_traj import make_ase_traj_parser
from xtalate.schema import Constraint


def _write_traj(images: list[Atoms]) -> bytes:
    buf = io.BytesIO()
    writer = TrajectoryWriter(buf, "w")
    for atoms in images:
        writer.write(atoms)
    return buf.getvalue()


def _rich_atoms() -> Atoms:
    atoms = Atoms(
        symbols=["H", "O", "H"],
        positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.98], [0.0, 0.93, -0.26]],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )
    atoms.set_masses([1.008, 15.999, 1.008])
    atoms.set_velocities(np.full((3, 3), 0.01))
    atoms.set_constraint(FixAtoms(indices=[0, 2]))
    atoms.info["step"] = 7
    atoms.calc = SinglePointCalculator(atoms, energy=-14.2, forces=np.zeros((3, 3)))
    return atoms


def test_capabilities_declare_read_and_write() -> None:
    read = make_ase_traj_parser().capabilities()
    write = make_ase_traj_exporter().capabilities()
    assert read.format_id == "ase_traj" and read.direction == "read"
    assert write.format_id == "ase_traj" and write.direction == "write"
    assert read.max_frames is None  # a trajectory format
    assert "fixed_atoms" in write.representable_constraint_kinds


def test_sniff_recognises_ulm_magic() -> None:
    parser = make_ase_traj_parser()
    data = _write_traj([Atoms("H", positions=[[0, 0, 0]])])
    assert parser.sniff(data[:64], "relax.traj") == 1.0
    assert parser.sniff(b"not a traj", None) == 0.0


def test_in_memory_roundtrip_preserves_rich_fields() -> None:
    parser = make_ase_traj_parser()
    exporter = make_ase_traj_exporter()
    data = _write_traj([_rich_atoms()])

    result = parser.parse(io.BytesIO(data), filename="relax.traj")
    frame = result.canonical.frames[0]
    assert frame.atoms.symbols == ["H", "O", "H"]
    assert frame.cell is not None and frame.cell.pbc == (True, True, True)
    assert frame.atoms.masses is not None
    assert frame.dynamics.velocities is not None
    assert frame.dynamics.forces is not None
    assert frame.electronic.total_energy == -14.2
    assert frame.dynamics.constraints == [
        Constraint(kind="fixed_atoms", atom_indices=[0, 2], parameters={})
    ]

    # ase_traj -> canonical -> ase_traj -> canonical reproduces the scientific content.
    out = io.BytesIO()
    exporter.export(result.canonical, out)
    reparsed = parser.parse(io.BytesIO(out.getvalue()), filename="relax.traj").canonical
    rf = reparsed.frames[0]
    assert rf.dynamics.velocities is not None and frame.dynamics.velocities is not None
    np.testing.assert_allclose(rf.atoms.positions, frame.atoms.positions)
    np.testing.assert_allclose(rf.dynamics.velocities, frame.dynamics.velocities)
    assert rf.electronic.total_energy == frame.electronic.total_energy
    assert rf.dynamics.constraints == frame.dynamics.constraints
    parser_version = reparsed.provenance.history[0].parser_version
    assert parser_version is not None
    assert parser_version.startswith("ase_traj-parser")
    assert "ase " in parser_version


def test_exports_to_other_formats() -> None:
    """A parsed .traj exports through the POSCAR and extXYZ exporters without error (the write
    side of the Capability Matrix, exercised end to end). No constraints here — POSCAR's exporter
    rightly refuses a fixed_atoms mask it cannot express when called outside the Conversion Engine's
    pre-flight, which is a separate concern from format breadth."""
    parser = make_ase_traj_parser()
    plain = Atoms(
        symbols=["H", "O", "H"],
        positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.98], [0.0, 0.93, -0.26]],
        cell=[10.0, 10.0, 10.0],
        pbc=True,
    )
    data = _write_traj([plain])
    canonical = parser.parse(io.BytesIO(data), filename="relax.traj").canonical

    poscar_out = io.BytesIO()
    make_poscar_exporter().export(canonical, poscar_out)
    assert b"Cartesian" in poscar_out.getvalue()

    extxyz_out = io.BytesIO()
    ExtxyzExporter().export(canonical, extxyz_out)
    assert b"Lattice" in extxyz_out.getvalue()
