"""Shared LAMMPS core unit tests (v1.3 M46-S1; Part 3 §7.2).

S1's core is exercised directly against **hand-verified** fixtures — no parser yet (that
is S2). Every unit-table factor is checked against the LAMMPS `units` documentation's
per-style rows and a hand-worked value, and cross-checked against ``ase.units`` (the
same NIST constants LAMMPS uses); the triclinic box mapping is exact against a
hand-computed fixture including the bounding-box inversion the dump format requires;
the type↔species helper validates two-sided against observed type counts; and the
coordinate resolver picks the right interpretation per column set.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import numpy as np
import pytest
from ase import units as ase_units

from xtalate.sdk.lammps import (
    UNIT_STYLES,
    box_from_bounds,
    coordinate_note,
    resolve_coordinate_columns,
    resolve_species,
    scaled_to_cartesian,
)
from xtalate.sdk.lammps.columns import CoordinateKind

# --- per-style unit tables (hand-verified against the LAMMPS units doc) ---------------


def test_metal_factors_are_hand_verified() -> None:
    # LAMMPS units doc, style metal: distance Å, time ps, energy eV, velocity Å/ps.
    metal = UNIT_STYLES["metal"]
    assert metal.distance_to_angstrom == 1.0
    assert metal.time_to_femtosecond == 1e3  # 1 ps = 1e3 fs
    assert metal.energy_to_electronvolt == 1.0
    assert metal.velocity_to_angstrom_per_femtosecond == 1e-3  # 1 Å/ps = 1e-3 Å/fs


def test_real_factors_are_hand_verified() -> None:
    # LAMMPS units doc, style real: distance Å, time fs, energy kcal/mol (thermochemical
    # 4.184 J), velocity Å/fs.
    real = UNIT_STYLES["real"]
    assert real.distance_to_angstrom == 1.0
    assert real.time_to_femtosecond == 1.0
    # 1 kcal/mol per molecule in eV: 4184 J / (6.02214076e23 × 1.602176634e-19) — the
    # same NIST constants ase.units embeds, so the two must agree to the last bit.
    assert real.energy_to_electronvolt == pytest.approx(
        ase_units.kcal / ase_units.mol / ase_units.eV
    )
    assert real.energy_to_electronvolt == pytest.approx(0.0433641, rel=1e-6)
    assert real.velocity_to_angstrom_per_femtosecond == 1.0


def test_si_factors_are_hand_verified() -> None:
    # LAMMPS units doc, style si: distance m, time s, energy J, velocity m/s.
    si = UNIT_STYLES["si"]
    assert si.distance_to_angstrom == 1e10  # 1 m = 1e10 Å
    assert si.time_to_femtosecond == 1e15  # 1 s = 1e15 fs
    assert si.energy_to_electronvolt == pytest.approx(ase_units.J / ase_units.eV)
    assert si.velocity_to_angstrom_per_femtosecond == 1e-5  # 1 m/s = 1e10 Å / 1e15 fs


def test_worked_value_conversions_per_style() -> None:
    """A hand-worked value through each factor, asserting the *meaning* not just the
    constant: a metal trajectory's 2.5 Å position stays 2.5 Å; a real run's 1 kcal/mol
    becomes ~0.0434 eV; an si run's 1 m box edge becomes 1e10 Å."""
    metal, real, si = UNIT_STYLES["metal"], UNIT_STYLES["real"], UNIT_STYLES["si"]
    # metal: position 2.5 Å → 2.5 Å; a 1.0 ps step → 1000 fs; 1.0 Å/ps → 1e-3 Å/fs.
    assert 2.5 * metal.distance_to_angstrom == 2.5
    assert 1.0 * metal.time_to_femtosecond == 1000.0
    assert 1.0 * metal.velocity_to_angstrom_per_femtosecond == 1e-3
    # real: 1 kcal/mol → 0.0433641 eV; 3.0 Å/fs stays 3.0 Å/fs.
    assert 1.0 * real.energy_to_electronvolt == pytest.approx(0.0433641, rel=1e-6)
    assert 3.0 * real.velocity_to_angstrom_per_femtosecond == 3.0
    # si: 1 m box edge → 1e10 Å; 1 s → 1e15 fs; 1 m/s → 1e-5 Å/fs; 1 J → 6.2415e18 eV.
    assert 1.0 * si.distance_to_angstrom == 1e10
    assert 1.0 * si.time_to_femtosecond == 1e15
    assert 1.0 * si.velocity_to_angstrom_per_femtosecond == 1e-5
    assert 1.0 * si.energy_to_electronvolt == pytest.approx(6.241509074460763e18)


def test_every_style_carries_a_human_readable_summary() -> None:
    assert UNIT_STYLES["metal"].summary == "Å, ps, eV"
    assert UNIT_STYLES["real"].summary == "Å, fs, kcal/mol"
    assert UNIT_STYLES["si"].summary == "m, s, J"


# --- triclinic box ↔ lattice (hand-computed fixtures, incl. the bound-vs-edge inversion)


def test_orthogonal_box_is_the_tilt_zero_case() -> None:
    box = box_from_bounds(0.0, 10.0, 0.0, 8.0, 0.0, 6.0)
    np.testing.assert_allclose(box.lattice, np.diag([10.0, 8.0, 6.0]))
    np.testing.assert_allclose(box.origin, [0.0, 0.0, 0.0])


def test_triclinic_box_inverts_the_bounding_box_exactly() -> None:
    """A restricted triclinic box xlo..zhi = 0..10, 0..8, 0..6 with tilts xy=2, xz=1,
    yz=0.5 has edge vectors a=(10,0,0), b=(2,8,0), c=(1,0.5,6) — but its dump writes the
    *bounding box* 0..13, 0..8.5, 0..6 (Howto_triclinic's formulas: xhi_bound = 10 +
    max(0,2,1,3) = 13; yhi_bound = 8 + max(0,0.5) = 8.5). Feeding the dump values must
    recover the restricted edge lengths, not naively take xhi_bound − xlo_bound = 13."""
    box = box_from_bounds(0.0, 13.0, 0.0, 8.5, 0.0, 6.0, xy=2.0, xz=1.0, yz=0.5)
    np.testing.assert_allclose(box.lattice, [[10.0, 0.0, 0.0], [2.0, 8.0, 0.0], [1.0, 0.5, 6.0]])
    np.testing.assert_allclose(box.origin, [0.0, 0.0, 0.0])


def test_triclinic_box_with_negative_tilts_inverts_correctly() -> None:
    """Same restricted box with negative tilts xy=-1, xz=-2, yz=-0.5: the bounding box
    extends *below* the origin (xlo_bound = 0 + min(0,-1,-2,-3) = -3; ylo_bound = 0 +
    min(0,-0.5) = -0.5), and the inversion must recover the restricted 0-based origin."""
    box = box_from_bounds(-3.0, 10.0, -0.5, 8.0, 0.0, 6.0, xy=-1.0, xz=-2.0, yz=-0.5)
    np.testing.assert_allclose(box.lattice, [[10.0, 0.0, 0.0], [-1.0, 8.0, 0.0], [-2.0, -0.5, 6.0]])
    np.testing.assert_allclose(box.origin, [0.0, 0.0, 0.0])


def test_triclinic_box_with_nonzero_origin() -> None:
    """A shifted box: restricted xlo=2 (so xhi=12), tilts xy=2, xz=1, yz=0.5 → dump
    bounds 2..15, 0..8.5, 0..6. The inversion must recover origin (2, 0, 0)."""
    box = box_from_bounds(2.0, 15.0, 0.0, 8.5, 0.0, 6.0, xy=2.0, xz=1.0, yz=0.5)
    np.testing.assert_allclose(box.lattice, [[10.0, 0.0, 0.0], [2.0, 8.0, 0.0], [1.0, 0.5, 6.0]])
    np.testing.assert_allclose(box.origin, [2.0, 0.0, 0.0])


def test_scaled_to_cartesian_matches_lammps_own_mapping() -> None:
    """A scaled point (0.5, 0.25, 1/6) in the triclinic box (tilts 2, 1, 0.5) maps to
    Cartesian exactly as LAMMPS does: x = xlo + sx·lx + sy·xy + sz·xz = 5 + 0.5 + 1/6,
    y = ylo + sy·ly + sz·yz = 2 + 1/24, z = zlo + sz·lz = 1."""
    box = box_from_bounds(0.0, 13.0, 0.0, 8.5, 0.0, 6.0, xy=2.0, xz=1.0, yz=0.5)
    scaled = np.array([[0.5, 0.25, 1.0 / 6.0]])
    out = scaled_to_cartesian(scaled, box)
    np.testing.assert_allclose(out, [[5.0 + 0.5 + 1.0 / 6.0, 2.0 + 1.0 / 12.0, 1.0]])


def test_scaled_to_cartesian_respects_the_origin() -> None:
    box = box_from_bounds(2.0, 15.0, 0.0, 8.5, 0.0, 6.0, xy=2.0, xz=1.0, yz=0.5)
    scaled = np.array([[0.5, 0.25, 1.0 / 6.0]])
    out = scaled_to_cartesian(scaled, box)
    np.testing.assert_allclose(out, [[2.0 + 5.0 + 0.5 + 1.0 / 6.0, 2.0 + 1.0 / 12.0, 1.0]])


# --- type↔species (feeds the existing missing_species) --------------------------------


def test_element_column_resolves_directly() -> None:
    symbols = resolve_species(type_values=None, element_column=["Si", "O", "Si"], species_map=None)
    assert symbols == ["Si", "O", "Si"]


def test_element_column_rejects_an_unknown_symbol() -> None:
    with pytest.raises(ValueError, match="not a valid element symbol"):
        resolve_species(type_values=None, element_column=["Si", "Zz"], species_map=None)


def test_type_column_resolves_under_a_species_map() -> None:
    types = np.array([1, 2, 1, 2], dtype=int)
    symbols = resolve_species(type_values=types, element_column=None, species_map={1: "Si", 2: "O"})
    assert symbols == ["Si", "O", "Si", "O"]


def test_type_column_refuses_without_a_species_map() -> None:
    with pytest.raises(ValueError, match="species_map"):
        resolve_species(type_values=np.array([1, 1]), element_column=None, species_map=None)


def test_type_column_refuses_an_unmapped_observed_type() -> None:
    types = np.array([1, 2, 3], dtype=int)
    with pytest.raises(ValueError, match="does not name observed type\\(s\\) \\[2, 3\\]"):
        resolve_species(type_values=types, element_column=None, species_map={1: "Si"})


def test_type_column_refuses_a_mismatched_map_with_extra_types() -> None:
    types = np.array([1, 2], dtype=int)
    with pytest.raises(ValueError, match="does not match this dump"):
        resolve_species(
            type_values=types, element_column=None, species_map={1: "Si", 2: "O", 3: "C"}
        )


def test_type_column_accepts_a_list_map_indexed_by_type() -> None:
    types = np.array([1, 2, 2], dtype=int)
    symbols = resolve_species(type_values=types, element_column=None, species_map=["Si", "O"])
    assert symbols == ["Si", "O", "O"]


def test_type_column_resolves_string_keys_that_coerce_to_int() -> None:
    types = np.array([1, 2], dtype=int)
    # The CLI --recover path passes string-typed parameters; the helper coerces them.
    string_map = cast(Mapping[int, str], {"1": "Si", "2": "O"})
    symbols = resolve_species(type_values=types, element_column=None, species_map=string_map)
    assert symbols == ["Si", "O"]


def test_type_column_rejects_invalid_symbols_and_non_integer_types() -> None:
    with pytest.raises(ValueError, match="not a valid element symbol"):
        resolve_species(
            type_values=np.array([1], dtype=int),
            element_column=None,
            species_map={1: "Zz"},
        )
    with pytest.raises(ValueError, match="positive integers"):
        resolve_species(
            type_values=np.array([1.5], dtype=float),
            element_column=None,
            species_map={1: "Si"},
        )


def test_no_species_information_refuses() -> None:
    with pytest.raises(ValueError, match="no species information"):
        resolve_species(type_values=None, element_column=None, species_map=None)


# --- coordinate-column semantics ------------------------------------------------------


def test_coordinate_resolver_picks_the_right_family() -> None:
    assert resolve_coordinate_columns(["id", "x", "y", "z"]).kind is CoordinateKind.CARTESIAN
    assert resolve_coordinate_columns(["id", "xs", "ys", "zs"]).kind is CoordinateKind.SCALED
    assert resolve_coordinate_columns(["id", "xu", "yu", "zu"]).kind is CoordinateKind.UNWRAPPED


def test_coordinate_resolver_refuses_none_and_ambiguous_sets() -> None:
    with pytest.raises(ValueError, match="no complete coordinate column family"):
        resolve_coordinate_columns(["id", "x", "y"])  # incomplete — not a family
    with pytest.raises(ValueError, match="more than one coordinate column family"):
        resolve_coordinate_columns(["id", "x", "y", "z", "xs", "ys", "zs"])


def test_coordinate_note_names_the_interpretation() -> None:
    assert "wrapped Cartesian" in coordinate_note(CoordinateKind.CARTESIAN)
    assert "scaled" in coordinate_note(CoordinateKind.SCALED)
    assert "unwrapped Cartesian" in coordinate_note(CoordinateKind.UNWRAPPED)
