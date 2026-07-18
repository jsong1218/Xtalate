"""ASE trajectory (``.traj``) parser tests — the M14B default-laundering suite (HARD GATE).

The headline suite here is **default-laundering** (Part 3 §2, Part 8 §1.1), exactly as for
``test_extxyz.py``: ASE always hands back a fully-populated ``Atoms`` object, so the parser's job
is to turn the library's invented defaults — a zero cell, ``pbc``, zeroed momenta, atomic-number
derived masses, an empty constraints list — back into ``None``. These are the highest-value tests
in the project: they guard the one place the absence convention (P3) is most likely to be violated
silently.

The final test is the **ASE-version canary** (M14 deliverable 3, DECISIONS.md D59): the installed
ASE must satisfy the ``pyproject.toml`` pin, and the wrapped version chosen in 14A must appear in
``provenance.history[0].parser_version`` of a parsed object — so a pin bump that changes parse
behaviour cannot slip past the gate unrecorded.
"""

from __future__ import annotations

import io
import tomllib
from pathlib import Path

import ase
import numpy as np
from ase import Atoms
from ase import units as ase_units
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixAtoms, FixBondLength
from ase.data import atomic_masses, atomic_numbers
from ase.io.trajectory import TrajectoryWriter
from packaging.requirements import Requirement
from packaging.version import Version

from tests._format_helpers import parse_bytes
from xtalate.parsers.ase_traj import AseTrajParser, make_ase_traj_parser
from xtalate.schema import Constraint


def _parser() -> AseTrajParser:
    return make_ase_traj_parser()


def _traj_bytes(*images: Atoms) -> bytes:
    """Serialise one or more ASE ``Atoms`` images to in-memory ``.traj`` bytes (the ULM
    container), mirroring how ``test_extxyz`` builds tiny in-line fixtures."""
    buf = io.BytesIO()
    writer = TrajectoryWriter(buf, "w")
    for atoms in images:
        writer.write(atoms)
    return buf.getvalue()


def _first_frame(*images: Atoms):  # type: ignore[no-untyped-def]
    obj = parse_bytes(_parser(), _traj_bytes(*images), filename="relax.traj").canonical
    return obj.frames[0]


# --- default-laundering suite (the point of an ASE-backed parser) ---------------------


def test_launder_absent_cell_to_none() -> None:
    # No cell written: ASE fabricates an all-zero 3x3; the canonical object must record None.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    assert _first_frame(atoms).cell is None


def test_launder_absent_momenta_to_none() -> None:
    # No momenta: ASE synthesises zeroed momenta; velocities must stay absent.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    assert _first_frame(atoms).dynamics.velocities is None


def test_launder_absent_masses_to_none() -> None:
    # ASE can always compute masses from atomic numbers; absence of a masses array is absence.
    atoms = Atoms("Fe", positions=[[0.0, 0.0, 0.0]])
    assert _first_frame(atoms).atoms.masses is None


def test_launder_absent_charges_and_magmoms_to_none() -> None:
    # No initial_charges / initial_magmoms arrays and no calculator: both stay absent.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    frame = _first_frame(atoms)
    assert frame.electronic.charges is None
    assert frame.electronic.magnetic_moments is None


def test_launder_empty_constraints_to_none() -> None:
    # ASE always exposes atoms.constraints as a (possibly empty) list; an empty list is a
    # manufactured default, not the source stating "explicitly no constraints" (D58 addendum).
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    assert _first_frame(atoms).dynamics.constraints is None


# --- field mapping (present-and-correct) ----------------------------------------------


def test_masses_present_when_written() -> None:
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    atoms.set_masses([2.014, 2.014])  # deuterium: a real, non-derived masses array
    masses = _first_frame(atoms).atoms.masses
    assert masses is not None
    np.testing.assert_allclose(masses, [2.014, 2.014])


def test_pbc_taken_verbatim_from_a_real_cell() -> None:
    # Unlike extXYZ, .traj always persists pbc alongside a cell, so it is taken verbatim (no
    # undeclared-pbc convention note): a genuinely mixed pbc must survive.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[4.0, 5.0, 6.0], pbc=[True, False, True])
    cell = _first_frame(atoms).cell
    assert cell is not None
    np.testing.assert_allclose(np.diag(cell.lattice_vectors), [4.0, 5.0, 6.0])
    assert cell.pbc == (True, False, True)


def test_velocities_unit_converted_from_momenta() -> None:
    # momenta = mass * velocity (ASE units); a velocity set in Å/(ASE time) is read back and
    # converted to Å/fs by the ase.units.fs factor (mirrors extXYZ).
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    v_ase = np.array([[0.5, 0.0, 0.0]])
    atoms.set_velocities(v_ase)  # stores momenta = mass * v internally
    velocities = _first_frame(atoms).dynamics.velocities
    assert velocities is not None
    np.testing.assert_allclose(velocities, v_ase * ase_units.fs)


def test_momenta_survive_the_atomic_mass_factor() -> None:
    # A momentum of 1.0 on H gives velocity 1/m_H in ASE units → Å/fs by ase.units.fs.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    atoms.set_momenta([[1.0, 0.0, 0.0]])
    velocities = _first_frame(atoms).dynamics.velocities
    assert velocities is not None
    mass_h = atomic_masses[atomic_numbers["H"]]
    assert np.isclose(velocities[0, 0], (1.0 / mass_h) * ase_units.fs)


def test_fixatoms_maps_to_fixed_atoms_constraint() -> None:
    atoms = Atoms("H3", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9], [0.0, 0.0, 1.8]])
    atoms.set_constraint(FixAtoms(indices=[0, 2]))
    constraints = _first_frame(atoms).dynamics.constraints
    assert constraints == [Constraint(kind="fixed_atoms", atom_indices=[0, 2], parameters={})]


def test_initial_charges_and_magmoms_map_to_electronic() -> None:
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    atoms.set_initial_charges([-0.3, 0.3])
    atoms.set_initial_magnetic_moments([1.0, -1.0])
    frame = _first_frame(atoms)
    assert frame.electronic.charges is not None
    assert frame.electronic.magnetic_moments is not None
    np.testing.assert_allclose(frame.electronic.charges, [-0.3, 0.3])
    np.testing.assert_allclose(frame.electronic.magnetic_moments, [1.0, -1.0])


def test_energy_and_forces_map_to_canonical_fields() -> None:
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    atoms.calc = SinglePointCalculator(atoms, energy=-3.5, forces=[[0.1, 0.2, 0.3]])
    frame = _first_frame(atoms)
    assert frame.electronic.total_energy == -3.5
    assert frame.dynamics.forces is not None
    np.testing.assert_allclose(frame.dynamics.forces[0], [0.1, 0.2, 0.3])


def test_stress_carried_not_mapped_to_electronic_stress() -> None:
    # Sign-convention safety (DECISIONS.md D18): stress is carried verbatim, not mapped.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[3.0, 3.0, 3.0], pbc=True)
    atoms.calc = SinglePointCalculator(atoms, stress=[1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
    obj = parse_bytes(_parser(), _traj_bytes(atoms), filename="relax.traj").canonical
    assert obj.frames[0].electronic.stress is None
    assert "ase_traj:stress" in obj.user_metadata.custom_per_frame


def test_non_fixatoms_constraint_is_carried_with_warning() -> None:
    # Only FixAtoms is modelled in v0.3 (M14 cut line, D58): a FixBondLength must not fabricate a
    # canonical constraint, and the parser must warn rather than drop it silently (P1).
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    atoms.set_constraint(FixBondLength(0, 1))
    result = parse_bytes(_parser(), _traj_bytes(atoms), filename="relax.traj")
    assert result.canonical.frames[0].dynamics.constraints is None
    assert any(i.code == "ASE_TRAJ_CONSTRAINT_NOT_MODELLED" for i in result.issues)


# --- ASE-version canary (M14 deliverable 3, D59) --------------------------------------


def _ase_pin() -> Requirement:
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    for dep in pyproject["project"]["dependencies"]:
        req = Requirement(dep)
        if req.name == "ase":
            return req
    raise AssertionError("no 'ase' dependency found in pyproject.toml")


def test_installed_ase_satisfies_the_declared_pin() -> None:
    # If a pin bump admits an ASE whose parse behaviour differs, this canary must be re-checked
    # against the laundering suite above before the pin is widened.
    assert _ase_pin().specifier.contains(Version(ase.__version__), prereleases=True)


def test_wrapped_ase_version_is_recorded_in_provenance() -> None:
    frame_obj = parse_bytes(
        _parser(), _traj_bytes(Atoms("H", positions=[[0, 0, 0]])), filename="relax.traj"
    ).canonical
    parser_version = frame_obj.provenance.history[0].parser_version
    assert parser_version is not None
    assert parser_version.startswith("ase_traj-parser")
    assert f"ase {ase.__version__}" in parser_version
