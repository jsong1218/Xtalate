"""Capability table-sync for the ``lammps_data`` write rows (v1.3 M48-S2; Part 3 §3, §4).

M48-S2 closes the M48-S1 parser-only staging state with the data *exporter* (D181): ``lammps_data``
becomes a full read+write format. This pins the write-side declarations the Part 3 §3 table and the
Part 4 §4 write declarations must match — the table-sync discipline (Part 8 §1.1):

* element column → type map (FULL symbols) and the per-type ``Masses`` table (FULL masses — a data
  file, unlike a dump, *requires* masses, so the field is written, not NONE);
* positions FULL (unit-converted), charges FULL (the charge/full styles), velocities
  FULL-but-only-when-present;
* lattice PARTIAL (restricted triclinic form only);
* ``requires_units_style=True`` (the write-side ``ambiguous_units`` trigger, target-identity keyed);
* ``holds_image_flags=True`` — a data file writes ``ix iy iz`` back, so data→data preserves the
  unwrapping payload;
* ``allows_open_boundaries=False`` — a data file always states a box;
* an **exact** writable-key list (not a name pattern): a data file's per-atom carries are a fixed
  set (id/type/molecule-id/image-flags), unlike a dump's open-ended compute columns.
"""

from __future__ import annotations

from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel
from xtalate.sdk.image_flags import IMAGE_FLAGS_CARRY_KEY

MATRIX = default_registry().capability_matrix()
EXPORTER = default_registry().get_exporter("lammps_data")


def test_write_symbols_positions_masses_charges_are_full() -> None:
    for path in ("atoms.symbols", "atoms.positions", "atoms.masses", "electronic.charges"):
        assert MATRIX.field_capability("lammps_data", "write", path).level is CapabilityLevel.FULL


def test_write_lattice_is_partial_restricted_triclinic() -> None:
    cap = MATRIX.field_capability("lammps_data", "write", "cell.lattice_vectors")
    assert cap.level is CapabilityLevel.PARTIAL
    assert "restricted" in (cap.notes or "")


def test_write_velocities_declared_when_present() -> None:
    # FULL: a data file can always express the block; only-when-present is the absence
    # convention (P3), not a capability condition.
    assert MATRIX.field_capability("lammps_data", "write", "dynamics.velocities").level is (
        CapabilityLevel.FULL
    )


def test_write_energetics_stay_none() -> None:
    for path in (
        "electronic.total_energy",
        "electronic.stress",
        "dynamics.forces",
        "electronic.magnetic_moments",
    ):
        assert MATRIX.field_capability("lammps_data", "write", path).level is CapabilityLevel.NONE


def test_write_requires_a_declared_unit_style() -> None:
    caps = EXPORTER.capabilities()
    assert caps.requires_units_style is True
    assert MATRIX.get("lammps_data", "write").requires_units_style is True


def test_write_side_holds_image_flags() -> None:
    caps = EXPORTER.capabilities()
    assert caps.holds_image_flags is True
    assert MATRIX.get("lammps_data", "write").holds_image_flags is True


def test_write_writable_custom_key_spellings_are_an_exact_list() -> None:
    caps = EXPORTER.capabilities()
    assert caps.writable_custom_keys == {
        "user_metadata.custom_global": [
            "lammps_data:comment",
            "lammps_data:units",
            "lammps_data:topology",
        ],
        "user_metadata.custom_per_atom": [
            "lammps_data:id",
            "lammps_data:type",
            "lammps_data:molecule_id",
            IMAGE_FLAGS_CARRY_KEY,
        ],
    }
    # A data file's per-atom carries are a fixed set, so there is no open-ended name pattern.
    assert "user_metadata.custom_per_atom" not in (caps.writable_custom_key_pattern or {})


def test_required_fields_and_boundaries() -> None:
    caps = EXPORTER.capabilities()
    assert set(caps.required_fields) == {
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
        "atoms.masses",
    }
    # A data file always states a box → open cells are not allowed.
    assert caps.allows_open_boundaries is False
    assert caps.representable_constraint_kinds == []


def test_read_rows_unchanged_from_m48_s1() -> None:
    # The S1 parser row is untouched by adding the exporter.
    assert MATRIX.get("lammps_data", "read").holds_image_flags is True
