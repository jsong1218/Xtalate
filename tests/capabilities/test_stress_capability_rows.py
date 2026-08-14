"""Capability table-sync for the `electronic.stress` rows (M40-S2, M42-S5; Part 3 §3, §4.2).

M40-S2 promotes extXYZ stress from carried-not-mapped to a first-class field: the read side can
populate `electronic.stress` when the `ambiguous_stress_convention` recovery resolves the sign
convention, and the write side writes it back (sign-reversed to the ASE convention, with a
`STRESS_SIGN_CONVENTION_CHANGED` warning). M42-S5 (D163) extends the same promise to `ase_traj`
— the second ASE-backed format to join the shared stress-carry-key set. This pins the
declarations the Part 3 §3 table and the §4.2 read/write declarations must match — the
table-sync discipline (Part 8 §1.1): extXYZ and ASE traj `electronic.stress` are PARTIAL on
**both** sides with the scenario note, and every other Phase 1 format's stress row stays `none`
— no other format expresses stress.
"""

from __future__ import annotations

import pytest

from xtalate.registry import default_registry
from xtalate.sdk import CapabilityLevel

MATRIX = default_registry().capability_matrix()

# The Phase 1 format set (Part 3 §3). Every row except extXYZ and ase_traj must stay NONE.
_OTHER_FORMATS = ["xyz", "poscar", "contcar", "cif", "xdatcar"]


@pytest.mark.parametrize("direction", ["read", "write"])
def test_extxyz_declares_stress_partial_with_the_scenario_note(direction: str) -> None:
    cap = MATRIX.field_capability("extxyz", direction, "electronic.stress")
    assert cap.level is CapabilityLevel.PARTIAL
    assert cap.notes is not None
    # The condition is the recovery, named on both sides (the Part 3 §3 cell and the §4.2
    # declarations carry the same wording): never mapped or written silently.
    assert "ambiguous_stress_convention" in cap.notes


@pytest.mark.parametrize("direction", ["read", "write"])
def test_ase_traj_declares_stress_partial_with_the_scenario_note(direction: str) -> None:
    # M42-S5 (D163): ase_traj joins extXYZ — its stress carry resolves through the same
    # scenario, so its rows flip NONE → PARTIAL with the same scenario-note wording.
    cap = MATRIX.field_capability("ase_traj", direction, "electronic.stress")
    assert cap.level is CapabilityLevel.PARTIAL
    assert cap.notes is not None
    assert "ambiguous_stress_convention" in cap.notes


@pytest.mark.parametrize("format_id", _OTHER_FORMATS)
@pytest.mark.parametrize("direction", ["read", "write"])
def test_every_other_format_stays_none(format_id: str, direction: str) -> None:
    # No other Phase 1 format expresses stress — the Part 3 §3 column and the §4.2 declarations
    # stay `none`/○. (An undeclared row reads as NONE; the assertion is on the declared row.)
    cap = MATRIX.field_capability(format_id, direction, "electronic.stress")
    assert cap.level is CapabilityLevel.NONE, f"{format_id} {direction} stress must stay NONE"


@pytest.mark.parametrize(
    ("format_id", "carry_key"),
    [("extxyz", "extxyz:stress"), ("ase_traj", "ase_traj:stress")],
)
def test_stress_carrying_parsers_name_the_carry_for_validation(
    format_id: str, carry_key: str
) -> None:
    # The read declaration names the custom key the parser carries stress under (D18), so the
    # Validation Engine can find a planned field's value in the re-parse (D151). The keys are
    # the shared stress-carry-key set (D163).
    caps = default_registry().get_parser(format_id).capabilities()
    assert caps.carried_field_keys == {"electronic.stress": carry_key}


@pytest.mark.parametrize(
    ("format_id", "carry_key"),
    [("extxyz", "extxyz:stress"), ("ase_traj", "ase_traj:stress")],
)
def test_stress_carrying_exporter_declares_ase_output_convention(
    format_id: str, carry_key: str
) -> None:
    # The write declaration states the convention the exporter writes: ASE compression-positive,
    # the inverse of the canonical tension-positive — the machine-readable half of the
    # STRESS_SIGN_CONVENTION_CHANGED warning that lets validation compare the re-parse in
    # canonical space (D151). Vocabulary is the scenario's option codes (terminology binding).
    caps = default_registry().get_exporter(format_id).capabilities()
    assert caps.stress_output_convention == "ase_sign_convention"
