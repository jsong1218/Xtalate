"""pymatgen ``Structure`` adapter tests — round-trip, carry, provenance (v1.5 M57-S1).

The adapters are a library seam, not a registered format (DECISIONS.md D215): there is no
file, no sniff, and no report, so the round-trip is a direct
``Structure → Canonical → Structure`` equality proof — never a golden-corpus entry.
These tests run (not skip) whenever the `dev` extra is installed, which pins pymatgen;
the final test is the **pymatgen-version canary** (the D59 discipline applied to the
third wrapped library).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

pymatgen = pytest.importorskip("pymatgen", reason="pymatgen extra not installed")

import numpy as np  # noqa: E402
from packaging.requirements import Requirement  # noqa: E402
from packaging.version import Version  # noqa: E402
from pymatgen.core import Lattice, Species, Structure  # noqa: E402

from xtalate.adapters import from_pymatgen, to_pymatgen  # noqa: E402


def _cubic_fe_o(**site_properties: Any) -> Structure:
    return Structure(
        Lattice.cubic(3.0),
        ["Fe", "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        site_properties=site_properties or None,
    )


def test_roundtrip_preserves_geometry_species_and_lattice() -> None:
    structure = _cubic_fe_o()
    canonical = from_pymatgen(structure)
    assert canonical.frame_count == 1
    frame = canonical.frames[0]
    assert frame.atoms.symbols == ["Fe", "O"]
    np.testing.assert_allclose(frame.atoms.positions, structure.cart_coords)
    assert frame.cell is not None
    np.testing.assert_allclose(frame.cell.lattice_vectors, structure.lattice.matrix)
    assert frame.cell.pbc == (True, True, True)

    back = to_pymatgen(canonical)
    assert back.composition.reduced_formula == structure.composition.reduced_formula
    assert len(back) == len(structure)
    assert [s.symbol for s in back.species] == ["Fe", "O"]
    np.testing.assert_allclose(np.asarray(back.cart_coords), structure.cart_coords, atol=1e-12)
    np.testing.assert_allclose(
        np.asarray(back.lattice.matrix), structure.lattice.matrix, atol=1e-12
    )


def test_roundtrip_preserves_declared_site_properties() -> None:
    magmoms = [1.5, 0.0]
    velocities = [[0.1, 0.0, 0.0], [0.0, -0.2, 0.3]]
    per_site_charges = [0.5, -0.5]
    structure = _cubic_fe_o(magmom=magmoms, velocities=velocities, charge=per_site_charges)
    canonical = from_pymatgen(structure)
    frame = canonical.frames[0]
    assert frame.electronic.magnetic_moments is not None
    np.testing.assert_allclose(frame.electronic.magnetic_moments, magmoms)
    assert frame.dynamics.velocities is not None
    np.testing.assert_allclose(frame.dynamics.velocities, velocities)
    assert frame.electronic.charges is not None
    np.testing.assert_allclose(frame.electronic.charges, per_site_charges)

    back = to_pymatgen(canonical)
    for key, expected in (
        ("magmom", magmoms),
        ("velocities", velocities),
        ("charge", per_site_charges),
    ):
        np.testing.assert_allclose(
            np.asarray(back.site_properties[key], dtype=float), expected, atol=1e-12
        )


def test_partial_pbc_survives_and_is_not_promoted_to_fully_periodic() -> None:
    # A 2D/slab Structure: periodicity in a and b, none in c. Overwriting it to fully
    # periodic would silently alter scientific information (P1/P3), so it must survive both
    # into the Canonical Object and back out.
    slab = Structure(
        Lattice([[3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 15.0]], pbc=(True, True, False)),
        ["Si"],
        [[0.0, 0.0, 0.0]],
    )
    canonical = from_pymatgen(slab)
    assert canonical.frames[0].cell is not None
    assert canonical.frames[0].cell.pbc == (True, True, False)

    back = to_pymatgen(canonical)
    assert tuple(back.lattice.pbc) == (True, True, False)


def test_unmapped_site_property_carries_verbatim_under_namespace() -> None:
    # selective_dynamics is deliberately carried, never modelled: its per-axis booleans
    # would be silently flattened into whole-atom fixed_atoms constraints (P1).
    flags = [[False, False, False], [True, True, True]]
    structure = _cubic_fe_o(selective_dynamics=flags)
    canonical = from_pymatgen(structure)
    carried = canonical.user_metadata.custom_per_atom["pymatgen:selective_dynamics"]
    np.testing.assert_array_equal(np.asarray(carried), flags)

    back = to_pymatgen(canonical)
    np.testing.assert_array_equal(
        np.asarray(back.site_properties["selective_dynamics"], dtype=bool), flags
    )


def test_declared_oxidation_states_strip_from_symbols_and_carry_per_site() -> None:
    structure = Structure(
        Lattice.cubic(3.0),
        [Species("Fe", 2), Species("O", -2)],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    canonical = from_pymatgen(structure)
    frame = canonical.frames[0]
    # The symbol strips the decoration; the state itself is declared data and carries.
    assert frame.atoms.symbols == ["Fe", "O"]
    carried = canonical.user_metadata.custom_per_atom["pymatgen:oxidation_state"]
    assert list(carried) == pytest.approx([2.0, -2.0])
    back = to_pymatgen(canonical)
    assert [site.specie.symbol for site in back] == ["Fe", "O"]
    assert [site.specie.oxi_state for site in back] == pytest.approx([2.0, -2.0])
    # The state restores onto the species ONLY — never also as a spurious site property the
    # source never had (a round-trip infidelity).
    assert "oxidation_state" not in back.site_properties
    assert back.site_properties == structure.site_properties


def test_explicit_total_charge_carries_and_restores() -> None:
    structure = _cubic_fe_o()
    structure.set_charge(-1.0)
    canonical = from_pymatgen(structure)
    # No canonical net-charge field exists, so a genuinely-set total charge carries
    # verbatim (P1) rather than being dropped.
    assert canonical.user_metadata.custom_global["pymatgen:charge"] == pytest.approx(-1.0)

    back = to_pymatgen(canonical)
    assert float(back.charge) == pytest.approx(-1.0)


def test_provenance_stamp_records_in_memory_source_and_wrapped_version() -> None:
    canonical = from_pymatgen(_cubic_fe_o())
    provenance = canonical.provenance
    assert provenance.source_filename is None  # constructed programmatically
    assert provenance.source_format == "pymatgen"  # an in-memory label, not a format id
    assert provenance.original_coordinate_system == "fractional"  # pymatgen is frac-native
    record = provenance.history[0]
    assert record.operation == "parse"
    assert record.source_format == "pymatgen"
    assert record.target_format is None
    assert record.parser_version is not None
    assert f"(pymatgen {_installed_version()})" in record.parser_version


def _pyproject_requirement(name: str) -> Requirement | None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    for extra in ("dev", "pymatgen"):
        for dep in data["project"]["optional-dependencies"].get(extra, []):
            requirement = Requirement(dep)
            if requirement.name == name:
                return requirement
    return None


def _installed_version() -> str:
    from importlib.metadata import version

    return version("pymatgen")


def test_pymatgen_version_canary() -> None:
    """The installed pymatgen satisfies the pyproject pin (the D59 canary, third wrap)."""
    pin = _pyproject_requirement("pymatgen")
    assert pin is not None, "pymatgen must be pinned in pyproject.toml (extra + dev)"
    assert pin.specifier.contains(Version(_installed_version()), prereleases=True)
