"""pymatgen adapter laundering tests — the construction-default audit (v1.5 M57-S1).

The third wrapped-library laundering suite, after ASE ``.traj`` (D18/M14) and ASE ``.db``
(M55): pymatgen manufactures values on construction, and a fabricated value is not data —
it must become ``None``/absent, never enter the Canonical Object (P3). The audited
default-vs-set distinctions, each pinned below:

* a ``Structure``'s public ``charge`` fabricates 0 / the oxidation-state sum whenever the
  caller never set one (pymatgen's ``_charge`` stays ``None``) — laundered to absence;
* an empty ``site_properties`` is pymatgen's construction default, so no per-atom
  electronic/dynamics array may appear from nothing;
* oxidation-state-decorated species are *declared* in-memory data — carried, not
  laundered — but their manufactured *sum* (what ``.charge`` then reports) still is.
"""

from __future__ import annotations

import pytest

pymatgen = pytest.importorskip("pymatgen", reason="pymatgen extra not installed")

import numpy as np  # noqa: E402
from pymatgen.core import Lattice, Species, Structure  # noqa: E402

from xtalate.adapters import from_pymatgen  # noqa: E402


def _cubic_fe_o() -> Structure:
    return Structure(Lattice.cubic(3.0), ["Fe", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])


def test_default_structure_yields_no_fabricated_electronic_or_charge_data() -> None:
    canonical = from_pymatgen(_cubic_fe_o())
    frame = canonical.frames[0]
    # pymatgen reports charge == 0.0 for a structure whose caller never set one: that
    # zero is manufactured, so no net-charge and no per-atom electronic arrays appear.
    assert frame.electronic.charges is None
    assert frame.electronic.magnetic_moments is None
    assert frame.electronic.total_energy is None
    assert frame.dynamics.velocities is None
    assert frame.dynamics.forces is None
    assert canonical.user_metadata.custom_global == {}
    assert canonical.user_metadata.custom_per_atom == {}


def test_oxidation_state_sum_is_never_mapped_as_total_charge() -> None:
    structure = Structure(
        Lattice.cubic(4.0),
        [Species("Fe", 2), Species("O", -2)],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    assert float(structure.charge) == pytest.approx(0.0)  # the sum pymatgen fabricates
    canonical = from_pymatgen(structure)
    # The declared per-site states carry; the derived total never enters the object.
    assert list(canonical.user_metadata.custom_per_atom["pymatgen:oxidation_state"]) == [
        2,
        -2,
    ]
    assert "pymatgen:charge" not in canonical.user_metadata.custom_global


def test_genuinely_set_values_are_preserved_not_laundered() -> None:
    structure = _cubic_fe_o()
    structure.set_charge(-2.0)
    structure.add_site_property("magmom", [2.0, 1.0])
    canonical = from_pymatgen(structure)
    magmoms = canonical.frames[0].electronic.magnetic_moments
    assert magmoms is not None
    np.testing.assert_allclose(magmoms, [2.0, 1.0])
    assert canonical.user_metadata.custom_global["pymatgen:charge"] == pytest.approx(-2.0)


def test_empty_site_properties_is_a_default_not_an_explicit_none() -> None:
    structure = _cubic_fe_o()
    assert structure.site_properties == {}  # the construction default itself
    canonical = from_pymatgen(structure)
    assert all(
        key != "pymatgen:magmom" and key != "pymatgen:charge"
        for key in canonical.user_metadata.custom_per_atom
    )
