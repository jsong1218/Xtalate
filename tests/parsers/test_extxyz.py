"""extXYZ parser tests (M3c).

The headline suite here is **default-laundering** (Part 3 §2, Part 8 §1.1): ASE always hands
back a fully-populated ``Atoms`` object, so the parser's job is to turn the library's invented
defaults — zero cell, ``pbc=(T,T,T)``, zero momenta — back into ``None``. These are the
highest-value tests in the project: they guard the one place the absence convention (P3) is
most likely to be violated silently.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ase import units as ase_units
from ase.data import atomic_masses, atomic_numbers

from chembridge.parsers.extxyz import ExtxyzParser
from chembridge.sdk import ParseError
from tests._format_helpers import assert_matches_golden, parse_bytes

GOLDEN = Path(__file__).parent.parent / "golden" / "extxyz" / "co-in-cell"


def _parser() -> ExtxyzParser:
    return ExtxyzParser()


# --- golden fidelity ------------------------------------------------------------------


def test_golden_co_in_cell() -> None:
    source = (GOLDEN / "sample.extxyz").read_bytes()
    result = parse_bytes(_parser(), source, filename="sample.extxyz")
    assert result.issues == []
    assert_matches_golden(result.canonical, (GOLDEN / "expected.canonical.json").read_text())


# --- default-laundering suite (the point of an ASE-backed parser) ---------------------


def test_launder_absent_cell_to_none() -> None:
    # No Lattice= key: ASE fabricates an all-zero cell; the canonical object must record None.
    data = b"2\nProperties=species:S:1:pos:R:3\nO 0.0 0.0 0.0\nH 1.0 0.0 0.0\n"
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frames[0].cell is None


def test_launder_absent_momenta_to_none() -> None:
    # No momenta column: ASE synthesises zero momenta; velocities must stay absent.
    data = b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3 pbc="T T T"\nH 0 0 0\n'
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frames[0].dynamics.velocities is None


def test_launder_absent_masses_to_none() -> None:
    # ASE can always compute masses from atomic numbers; absence of a masses column is absence.
    data = b"1\nProperties=species:S:1:pos:R:3\nFe 0 0 0\n"
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frames[0].atoms.masses is None


def test_undeclared_pbc_uses_convention_and_is_recorded() -> None:
    # Lattice present but no pbc= key: keep the (real) cell, take the extXYZ convention for pbc,
    # and record that pbc was not declared (never pass a convention value off as source data).
    data = b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3\nH 0 0 0\n'
    obj = parse_bytes(_parser(), data).canonical
    cell = obj.frames[0].cell
    assert cell is not None
    assert cell.pbc == (True, True, True)
    assert any("pbc not declared" in note for note in obj.provenance.parse_notes)


def test_declared_pbc_is_taken_verbatim() -> None:
    data = b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3 pbc="T F T"\nH 0 0 0\n'
    obj = parse_bytes(_parser(), data).canonical
    cell = obj.frames[0].cell
    assert cell is not None
    assert cell.pbc == (True, False, True)
    assert not any("pbc not declared" in note for note in obj.provenance.parse_notes)


# --- field mapping (unit- and sign-safe) ----------------------------------------------


def test_velocities_unit_converted_from_momenta() -> None:
    # momenta = mass * velocity (ASE units); a momentum of 1.0 on H gives velocity 1/m_H in
    # ASE units, which the parser converts to Å/fs by the ase.units.fs factor.
    data = (
        b'1\nLattice="5 0 0 0 5 0 0 0 5" Properties=species:S:1:pos:R:3:momenta:R:3 pbc="T T T"\n'
        b"H 0 0 0 1.0 0.0 0.0\n"
    )
    obj = parse_bytes(_parser(), data).canonical
    v = obj.frames[0].dynamics.velocities
    assert v is not None
    mass_h = atomic_masses[atomic_numbers["H"]]
    assert np.isclose(v[0, 0], (1.0 / mass_h) * ase_units.fs)


def test_charge_column_maps_to_electronic_charges() -> None:
    data = (
        b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3:charge:R:1 pbc="T T T"\n'
        b"O 0 0 0 -0.8\n"
    )
    obj = parse_bytes(_parser(), data).canonical
    charges = obj.frames[0].electronic.charges
    assert charges is not None
    assert np.isclose(charges[0], -0.8)


def test_energy_and_forces_map_to_canonical_fields() -> None:
    data = (
        b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3:forces:R:3 '
        b'energy=-3.5 pbc="T T T"\nH 0 0 0 0.1 0.2 0.3\n'
    )
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frames[0].electronic.total_energy == -3.5
    forces = obj.frames[0].dynamics.forces
    assert forces is not None
    assert np.allclose(forces[0], [0.1, 0.2, 0.3])


def test_arbitrary_column_carries_to_custom_per_atom() -> None:
    data = b"1\nProperties=species:S:1:pos:R:3:my_label:R:1\nH 0 0 0 7.0\n"
    obj = parse_bytes(_parser(), data).canonical
    assert "extxyz:my_label" in obj.user_metadata.custom_per_atom
    column = np.asarray(obj.user_metadata.custom_per_atom["extxyz:my_label"])
    assert np.isclose(column[0], 7.0)


def test_comment_keyvalue_carries_to_custom_per_frame() -> None:
    data = b"1\nProperties=species:S:1:pos:R:3 config_type=slab\nH 0 0 0\n"
    obj = parse_bytes(_parser(), data).canonical
    assert obj.user_metadata.custom_per_frame["extxyz:config_type"] == ["slab"]


def test_stress_carried_not_mapped_to_electronic_stress() -> None:
    # Sign-convention safety (DECISIONS.md D18): stress is carried verbatim, not mapped.
    data = (
        b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
        b'stress="1 0 0 0 2 0 0 0 3" pbc="T T T"\nH 0 0 0\n'
    )
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frames[0].electronic.stress is None
    assert "extxyz:stress" in obj.user_metadata.custom_per_frame


# --- multi-frame ----------------------------------------------------------------------


def _frame(step: str, x: str) -> bytes:
    header = f'Lattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 pbc="T T T" step={step}'
    return f"1\n{header}\nH {x} 0 0\n".encode()


def test_multi_frame_is_a_trajectory() -> None:
    data = _frame("0", "0.0") + _frame("1", "0.1")
    obj = parse_bytes(_parser(), data).canonical
    assert obj.frame_count == 2
    assert obj.trajectory is not None
    assert obj.trajectory.timestep is None
    assert list(obj.user_metadata.custom_per_frame["extxyz:step"]) == [0.0, 1.0]


def test_variable_atom_count_across_frames_raises() -> None:
    data = (
        b"1\nProperties=species:S:1:pos:R:3\nH 0 0 0\n"
        b"2\nProperties=species:S:1:pos:R:3\nH 0 0 0\nH 1 0 0\n"
    )
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), data)
    assert exc.value.issues[0].code == "EXTXYZ_VARIABLE_ATOM_COUNT"


# --- sniff disambiguation (Part 3 §6.1) -----------------------------------------------


def test_sniff_recognises_extxyz_markers() -> None:
    data = b'2\nLattice="1 0 0 0 1 0 0 0 1" Properties=species:S:1:pos:R:3\nO 0 0 0\nH 1 0 0\n'
    assert _parser().sniff(data, "thing.xyz") >= 0.9


def test_sniff_yields_to_plain_xyz_without_markers() -> None:
    # A plain XYZ (no Lattice=/Properties=) should score low so the plain parser wins.
    assert _parser().sniff(b"1\njust a comment\nO 0 0 0\n", "thing.xyz") <= 0.3


def test_sniff_rejects_non_xyz() -> None:
    assert _parser().sniff(b"NaCl\n1.0\n 4 0 0\n", "POSCAR") == 0.0


# --- error contract (Part 3 §5) -------------------------------------------------------


def test_empty_file_raises() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), b"  \n\n")
    assert exc.value.issues[0].code == "EXTXYZ_EMPTY"


def test_malformed_file_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        parse_bytes(_parser(), b"5\nProperties=species:S:1:pos:R:3\nO 0 0 0\n")
    assert exc.value.issues[0].code == "EXTXYZ_PARSE_ERROR"
