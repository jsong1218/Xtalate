"""pymatgen adapter occupancy tests — partial site occupancy, both directions (v1.4/v1.5
review R6; D225).

Before R6 the pymatgen adapter never touched ``atoms.occupancies`` (DECISIONS D114 promotes
occupancy to a first-class canonical field precisely because partial occupancy is real
science): ``to_pymatgen`` silently wrote partial-occupancy sites as fully occupied, and
``from_pymatgen`` crashed with pymatgen's raw ``AttributeError`` on ``site.specie`` for any
disordered site. These tests pin the close of that gap:

* a single-species partial site (``Fe:0.8``) maps onto ``atoms.occupancies`` (full sites as
  ``1.0``, the field ``None`` only when nothing is partial) and round-trips back preserving
  the fraction as pymatgen's native per-site dict;
* a site disordered across *multiple* species is **refused** with a clear adapter message —
  ``atoms.occupancies`` holds one occupancy per atom, so there is no lossless spelling, and
  silently keeping one species would be a P1 drop;
* an *unknown* occupancy (a per-site ``None``, CIF '?') refuses rather than being silently
  treated as full (**P4**).

These are library-seam tests (D215): direct ``Structure/Molecule → Canonical → back``
round-trips, never a golden-corpus entry. They run whenever the ``dev`` extra's pymatgen
pin is installed, like the sibling M57 suites.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

pymatgen = pytest.importorskip("pymatgen", reason="pymatgen extra not installed")

import numpy as np  # noqa: E402
from pymatgen.core import Lattice, Molecule, Species, Structure  # noqa: E402

from xtalate.adapters import from_pymatgen, to_pymatgen  # noqa: E402
from xtalate.schema import AtomsBlock  # noqa: E402


def _atoms(frame: Any, occupancies: list[float | None]) -> AtomsBlock:
    """An AtomsBlock mirroring ``frame``'s geometry with the given occupancy list."""
    return AtomsBlock(
        symbols=frame.atoms.symbols,
        positions=frame.atoms.positions,
        occupancies=occupancies,
    )


def _partial_fe_o() -> Structure:
    return Structure(
        Lattice.cubic(3.0),
        [{"Fe": 0.8}, {"O": 1.0}],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )


def test_single_species_partial_occupancy_maps_onto_canonical_field() -> None:
    canonical = from_pymatgen(_partial_fe_o())
    frame = canonical.frames[0]
    # 0.8 is a declared partial claim; the full O site is spelled 1.0, not laundered to
    # absence, so the parallel list aligns atom-for-atom (the CIF discipline).
    assert frame.atoms.occupancies == pytest.approx([0.8, 1.0])
    assert frame.atoms.symbols == ["Fe", "O"]
    # No oxidation state was declared, so no derivation may appear either.
    assert canonical.user_metadata.custom_per_atom == {}


def test_partial_occupancy_roundtrips_through_to_pymatgen_preserving_fraction() -> None:
    canonical = from_pymatgen(_partial_fe_o())
    back = to_pymatgen(canonical)
    # pymatgen's native spelling of the partially-occupied site is a per-site composition
    # Fe0.8; the fraction must survive, not be promoted to a full Fe1 (the R6 regression).
    assert [str(site.species) for site in back.sites] == ["Fe0.8", "O1"]
    np.testing.assert_allclose(np.asarray(back.cart_coords), _partial_fe_o().cart_coords)


def test_full_occupancy_list_builds_bare_species_not_partial_dicts() -> None:
    canonical = from_pymatgen(_partial_fe_o())
    frame = canonical.frames[0]
    full = copy.deepcopy(canonical)
    full.frames = [frame.model_copy(update={"atoms": _atoms(frame, [1.0, 1.0])})]
    back = to_pymatgen(full)
    assert [str(site.species) for site in back.sites] == ["Fe1", "O1"]
    assert [site.is_ordered for site in back.sites] == [True, True]


def test_partial_occupancy_combines_with_declared_oxidation_state() -> None:
    structure = Structure(
        Lattice.cubic(3.0),
        [{Species("Fe", 2): 0.8}, {Species("O", -2): 1.0}],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    canonical = from_pymatgen(structure)
    frame = canonical.frames[0]
    assert frame.atoms.symbols == ["Fe", "O"]
    assert frame.atoms.occupancies == pytest.approx([0.8, 1.0])
    assert list(canonical.user_metadata.custom_per_atom["pymatgen:oxidation_state"]) == [
        pytest.approx(2.0),
        pytest.approx(-2.0),
    ]

    back = to_pymatgen(canonical)
    # The state and the fraction ride together on the one site: Fe2+:0.8, never one or
    # the other dropped. (The Fe site is not ordered, so its oxi state is read from the
    # per-site composition rather than the ``specie`` property, which raises on disorder.)
    assert [str(site.species) for site in back.sites] == ["Fe2+0.8", "O2-1"]
    restored_oxi = [
        next(iter(site.species.items()))[0].oxi_state for site in back.sites if site.species
    ]
    assert restored_oxi == pytest.approx([2.0, -2.0])


def test_mixed_species_disordered_site_refuses_not_attribute_error() -> None:
    # Fe/Zn dilution on one site: atoms.occupancies cannot express two species with
    # distinct occupancies on the same atom, so forge ahead would silently drop a species.
    structure = Structure(
        Lattice.cubic(3.0),
        [{"Fe": 0.5, "Zn": 0.5}, {"O": 1.0}],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    with pytest.raises(ValueError, match="atoms.occupancies holds one occupancy per atom"):
        from_pymatgen(structure)


def test_unknown_occupancy_refuses_instead_of_being_treated_as_full() -> None:
    # A per-site None occupancy (CIF '?'/'/') states the source withheld the value; a
    # pymatgen object has no way to say "unknown" without fabricating a fraction (P4).
    canonical = from_pymatgen(_partial_fe_o())
    frame = canonical.frames[0]
    unknown = copy.deepcopy(canonical)
    unknown.frames = [frame.model_copy(update={"atoms": _atoms(frame, [None, 1.0])})]
    with pytest.raises(ValueError, match="fabricating a fraction the source withheld"):
        to_pymatgen(unknown)


def test_partial_occupancy_roundtrips_on_a_molecule_too() -> None:
    molecule = Molecule([{"Fe": 0.8}, {"O": 1.0}], [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    canonical = from_pymatgen(molecule)
    assert canonical.frames[0].cell is None  # kept a Molecule end to end (D216)
    assert canonical.frames[0].atoms.occupancies == pytest.approx([0.8, 1.0])
    back = to_pymatgen(canonical)
    assert isinstance(back, Molecule)
    assert [str(site.species) for site in back.sites] == ["Fe0.8", "O1"]
