"""Capability table-sync for the `lammps_dump` write rows (v1.3 M47-S1; Part 3 §3, §4).

M47 closes the M46 parser-only staging state with the dump *exporter* (D177): `lammps_dump`
becomes the first full-axis format addition since v0.3. This pins the write-side declarations
the Part 3 §3 table and the §4 write declarations must match — the table-sync discipline
(Part 8 §1.1): element column + type map (FULL symbols), positions FULL (unit-converted),
lattice PARTIAL (restricted triclinic form), velocities FULL-but-only-when-present,
`requires_units_style=True` (the write-side `ambiguous_units` trigger), and — M47-S2 —
**image flags are written back** (`holds_image_flags=True` write), so dump→dump no longer
predicts the unwrapping loss while incumbent targets still do.
"""

from __future__ import annotations

from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel

MATRIX = default_registry().capability_matrix()
EXPORTER = default_registry().get_exporter("lammps_dump")


def test_write_symbols_and_positions_are_full() -> None:
    assert MATRIX.field_capability("lammps_dump", "write", "atoms.symbols").level is (
        CapabilityLevel.FULL
    )
    assert MATRIX.field_capability("lammps_dump", "write", "atoms.positions").level is (
        CapabilityLevel.FULL
    )


def test_write_lattice_is_partial_restricted_triclinic() -> None:
    cap = MATRIX.field_capability("lammps_dump", "write", "cell.lattice_vectors")
    assert cap.level is CapabilityLevel.PARTIAL
    assert "restricted" in (cap.notes or "")


def test_write_velocities_declared_when_present() -> None:
    # FULL: a dump can always express the block; the only-when-present behaviour is the
    # absence convention (P3), not a capability condition.
    assert MATRIX.field_capability("lammps_dump", "write", "dynamics.velocities").level is (
        CapabilityLevel.FULL
    )


def test_write_electronic_and_masses_stay_none() -> None:
    # Dumps carry no energies/forces/charges/moments (a compute column is a carried custom
    # column, never mapped) and no masses field.
    for path in (
        "electronic.total_energy",
        "electronic.stress",
        "electronic.charges",
        "electronic.magnetic_moments",
        "atoms.masses",
    ):
        assert MATRIX.field_capability("lammps_dump", "write", path).level is CapabilityLevel.NONE


def test_write_requires_a_declared_unit_style() -> None:
    # The name M47-S1's pre-flight arm reads: every dump write needs the ambiguous_units
    # choice resolved (target identity), so the target declares it machine-readably.
    caps = EXPORTER.capabilities()
    assert caps.requires_units_style is True
    assert MATRIX.get("lammps_dump", "write").requires_units_style is True


def test_s2_write_side_holds_image_flags() -> None:
    """S2 lands the capability with the writer behavior: dump→dump can preserve the
    unwrapping payload, while the read-side declaration remains unchanged."""
    caps = EXPORTER.capabilities()
    assert caps.holds_image_flags is True
    assert MATRIX.get("lammps_dump", "write").holds_image_flags is True
    assert MATRIX.get("lammps_dump", "read").holds_image_flags is True


def test_write_writable_custom_key_spellings() -> None:
    caps = EXPORTER.capabilities()
    # The resolved unit style is the one writable custom_global key (the ITEM: UNITS header);
    # the per-snapshot step number rides custom_per_frame; per-atom columns are open-ended
    # (a name pattern), including the structured image-flag carry.
    assert caps.writable_custom_keys == {
        "user_metadata.custom_global": ["lammps_dump:units"],
        "user_metadata.custom_per_frame": ["lammps_dump:timestep"],
    }
    pattern = caps.writable_custom_key_pattern["user_metadata.custom_per_atom"]
    import re

    assert re.fullmatch(pattern, "lammps_dump:c_pe") is not None
    assert re.fullmatch(pattern, "lammps_dump:image_flags") is not None
    assert re.fullmatch(pattern, "lammps_dump:id") is None
    assert re.fullmatch(pattern, "lammps_dump:type") is None
    assert re.fullmatch(pattern, "foreign:key") is None


def test_required_fields_and_boundaries() -> None:
    caps = EXPORTER.capabilities()
    assert set(caps.required_fields) == {
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
    }
    # A non-periodic axis is expressible (the f boundary flag) → open cells are allowed.
    assert caps.allows_open_boundaries is True
    # No constraint kinds, no energy/stress output.
    assert caps.representable_constraint_kinds == []


def test_read_rows_unchanged_from_m46() -> None:
    assert MATRIX.get("lammps_dump", "read").holds_image_flags is True
    assert MATRIX.field_capability("lammps_dump", "read", "atoms.symbols").level is (
        CapabilityLevel.PARTIAL
    )
