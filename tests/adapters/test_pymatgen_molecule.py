"""pymatgen ``Molecule`` adapter tests — the non-periodic case (v1.5 M57-S2; D216).

The ``cell``-presence rule end to end: a ``Molecule`` round-trips with ``cell = None``
throughout — **never a fabricated identity lattice** — and ``to_pymatgen`` dispatches on
the same fact (celled Canonical Object → ``Structure``, cell-less → ``Molecule``). The
``Molecule`` laundering cases pin pymatgen's always-populated ``_charge`` and its
manufactured default ``spin_multiplicity`` (``nelectrons % 2 + 1``) against entry into
the Canonical Object, and a multi-frame trajectory refuses rather than silently
exporting frame 0.
"""

from __future__ import annotations

import pytest

pymatgen = pytest.importorskip("pymatgen", reason="pymatgen extra not installed")

import numpy as np  # noqa: E402
from pymatgen.core import Lattice, Molecule, Structure  # noqa: E402

from xtalate.adapters import from_pymatgen, to_pymatgen  # noqa: E402
from xtalate.schema import CanonicalObject  # noqa: E402


def _water(**kwargs: object) -> Molecule:
    return Molecule(
        ["H", "O", "H"],
        [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, -0.3]],
        **kwargs,
    )


def _celled_canonical() -> CanonicalObject:
    return from_pymatgen(Structure(Lattice.cubic(3.0), ["Fe"], [[0.0, 0.0, 0.0]]))


def test_molecule_roundtrip_with_cell_none_end_to_end() -> None:
    molecule = _water()
    canonical = from_pymatgen(molecule)
    frame = canonical.frames[0]
    assert frame.cell is None, "a Molecule must never gain a fabricated lattice"
    assert canonical.provenance.original_coordinate_system == "cartesian"
    assert frame.atoms.symbols == ["H", "O", "H"]
    np.testing.assert_allclose(frame.atoms.positions, molecule.cart_coords)

    back = to_pymatgen(canonical)
    assert isinstance(back, Molecule)
    np.testing.assert_allclose(np.asarray(back.cart_coords), molecule.cart_coords, atol=1e-12)


def test_default_molecule_charge_and_spin_launder_to_absence() -> None:
    # pymatgen populates _charge = 0 and spin = nelectrons % 2 + 1 on construction; both
    # are manufactured, so neither may appear as data.
    molecule = _water()
    assert float(molecule.charge) == 0.0 and int(molecule.spin_multiplicity) == 1
    canonical = from_pymatgen(molecule)
    assert "pymatgen:charge" not in canonical.user_metadata.custom_global
    assert "pymatgen:spin_multiplicity" not in canonical.user_metadata.custom_global


def test_genuinely_nondefault_molecule_charge_and_spin_carry_and_restore() -> None:
    # A cationic doublet: charge 1 != manufactured 0, spin 2 == the manufactured default
    # for a charged water (nelectrons 9 -> 9 % 2 + 1 = 2), so only charge carries.
    cation = _water(charge=1)
    canonical = from_pymatgen(cation)
    assert canonical.user_metadata.custom_global["pymatgen:charge"] == pytest.approx(1.0)
    assert "pymatgen:spin_multiplicity" not in canonical.user_metadata.custom_global

    back = to_pymatgen(canonical)
    assert float(back.charge) == pytest.approx(1.0)


def test_triplet_spin_differs_from_manufactured_default_and_round_trips() -> None:
    triplet = _water(charge=0, spin_multiplicity=3)
    canonical = from_pymatgen(triplet)
    assert canonical.user_metadata.custom_global["pymatgen:spin_multiplicity"] == 3

    back = to_pymatgen(canonical)
    assert int(back.spin_multiplicity) == 3


def test_to_pymatgen_dispatches_on_cell_presence() -> None:
    assert isinstance(to_pymatgen(_celled_canonical()), Structure)
    cell_less = from_pymatgen(_water())
    assert cell_less.frames[0].cell is None
    assert isinstance(to_pymatgen(cell_less), Molecule)


def test_molecule_site_properties_and_oxidation_states_round_trip() -> None:
    molecule = _water()
    molecule.add_site_property("magmom", [0.0, 0.5, 0.0])
    canonical = from_pymatgen(molecule)
    magmoms = canonical.frames[0].electronic.magnetic_moments
    assert magmoms is not None
    np.testing.assert_allclose(magmoms, [0.0, 0.5, 0.0])

    back = to_pymatgen(canonical)
    np.testing.assert_allclose(
        np.asarray(back.site_properties["magmom"], dtype=float), [0.0, 0.5, 0.0]
    )


def test_trajectory_refuses_to_pymatgen() -> None:
    # Two frames of the same three atoms: a pymatgen object is a single structure, so an
    # honest refusal beats a silent frame-0 slice.
    water = from_pymatgen(_water())
    trajectory = water.model_copy(
        update={
            "frames": [water.frames[0], water.frames[0].model_copy(update={"index": 1})],
            "trajectory": water.trajectory.model_copy() if water.trajectory else None,
        }
    )
    with pytest.raises(ValueError, match="frame_selection"):
        to_pymatgen(trajectory)
