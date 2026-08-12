"""Capability table-sync for the `electronic.stress` rows (M40-S2, MASTER_SPEC Part 3 §3, §4.2).

M40-S2 promotes extXYZ stress from carried-not-mapped to a first-class field: the read side can
populate `electronic.stress` when the `ambiguous_stress_convention` recovery resolves the sign
convention, and the write side writes it back (sign-reversed to the ASE convention, with a
`STRESS_SIGN_CONVENTION_CHANGED` warning). This pins the declarations the Part 3 §3 table and the
§4.2 read/write declarations must match — the table-sync discipline (Part 8 §1.1): extXYZ
`electronic.stress` is PARTIAL on **both** sides with the scenario note (reversing Revision 1.6's
C1 correction, which set it to `none` precisely because stress was unmapped), and every other
Phase 1 format's stress row stays `none` — no other format expresses stress.
"""

from __future__ import annotations

import pytest

from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel

MATRIX = default_registry().capability_matrix()

# The Phase 1 format set (Part 3 §3). Every row except extXYZ must stay NONE.
_OTHER_FORMATS = ["xyz", "poscar", "contcar", "cif", "xdatcar", "ase_traj"]


@pytest.mark.parametrize("direction", ["read", "write"])
def test_extxyz_declares_stress_partial_with_the_scenario_note(direction: str) -> None:
    cap = MATRIX.field_capability("extxyz", direction, "electronic.stress")
    assert cap.level is CapabilityLevel.PARTIAL
    assert cap.notes is not None
    # The condition is the recovery, named on both sides (the Part 3 §3 cell and the §4.2
    # declarations carry the same wording): never mapped or written silently.
    assert "ambiguous_stress_convention" in cap.notes


@pytest.mark.parametrize("format_id", _OTHER_FORMATS)
@pytest.mark.parametrize("direction", ["read", "write"])
def test_every_other_format_stays_none(format_id: str, direction: str) -> None:
    # No other Phase 1 format expresses stress — the Part 3 §3 column and the §4.2 declarations
    # stay `none`/○. (An undeclared row reads as NONE; the assertion is on the declared row.)
    cap = MATRIX.field_capability(format_id, direction, "electronic.stress")
    assert cap.level is CapabilityLevel.NONE, f"{format_id} {direction} stress must stay NONE"


def test_extxyz_parser_names_the_carry_for_validation() -> None:
    # The read declaration names the custom key the parser carries stress under (D18), so the
    # Validation Engine can find a planned field's value in the re-parse (D151).
    caps = default_registry().get_parser("extxyz").capabilities()
    assert caps.carried_field_keys == {"electronic.stress": "extxyz:stress"}


def test_extxyz_exporter_declares_ase_output_convention() -> None:
    # The write declaration states the convention the exporter writes: ASE compression-positive,
    # the inverse of the canonical tension-positive — the machine-readable half of the
    # STRESS_SIGN_CONVENTION_CHANGED warning that lets validation compare the re-parse in
    # canonical space (D151). Vocabulary is the scenario's option codes (terminology binding).
    caps = default_registry().get_exporter("extxyz").capabilities()
    assert caps.stress_output_convention == "ase_sign_convention"
