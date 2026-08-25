"""Capability table-sync for the `ase_db` rows (M55-S1 read side; extended to write in S2).

M55 adds ``ase_db`` as the fourth ASE-backed format (MASTER_SPEC Part 3 §3). Its read side
mirrors ``ase_traj``: a single-row database parses to one structure, ``electronic.stress`` is
PARTIAL with the scenario note (carried until the ``ambiguous_stress_convention`` recovery
resolves the sign convention — D18/D163), the carry key joins the shared stress-carry key set,
and the per-row key-value carry makes ``user_metadata.custom_global`` FULL. This pins the
declarations the Part 3 §3 table and the §4.2 read declaration must match (Part 8 §1.1). The
write-direction rows land with the S2 exporter.
"""

from __future__ import annotations

from xtalate.registry import default_registry
from xtalate.sdk import STRESS_CARRY_KEYS, CapabilityLevel

MATRIX = default_registry().capability_matrix()


def test_ase_db_read_declares_stress_partial_with_the_scenario_note() -> None:
    cap = MATRIX.field_capability("ase_db", "read", "electronic.stress")
    assert cap.level is CapabilityLevel.PARTIAL
    assert cap.notes is not None
    # The condition is the recovery, named on both sides (the Part 3 §3 cell and the §4.2
    # declarations carry the same wording): never mapped silently.
    assert "ambiguous_stress_convention" in cap.notes


def test_ase_db_read_is_single_structure_and_names_the_stress_carry() -> None:
    caps = default_registry().get_parser("ase_db").capabilities()
    assert caps.format_id == "ase_db"
    assert caps.direction == "read"
    assert caps.max_frames == 1  # one row → one structure; multi-row refuses ASEDB_MULTIPLE_ROWS
    # The read declaration names the custom key the parser carries stress under (D18), so the
    # Validation Engine can find a planned field's value in the re-parse (D151).
    assert caps.carried_field_keys == {"electronic.stress": "ase_db:stress"}
    # The per-row key-value carry (Part 2 §6.1) is a first-class read surface.
    assert caps.fields["user_metadata.custom_global"].level is CapabilityLevel.FULL
    assert caps.fields["atoms.symbols"].level is CapabilityLevel.FULL
    assert caps.fields["atoms.positions"].level is CapabilityLevel.FULL


def test_ase_db_stress_key_joins_the_shared_carry_set() -> None:
    # The shared stress-carry key set (D163) is what the ambiguous_stress_convention detection
    # reads; a third ASE carry must be registered there, in the SDK, in exactly one place.
    assert "ase_db:stress" in STRESS_CARRY_KEYS
