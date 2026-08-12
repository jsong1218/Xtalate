"""`ambiguous_stress_convention` pre-flight + conversion wiring tests (M40, Part 3 §4.3, Part 4).

The detection is a **new shape**: stress is a source field that is *present* (parked in the
extXYZ custom carry) which the target *could* express as the canonical `electronic.stress` —
neither the fabricative \"required field absent\" shape nor the reductive \"present field the
target cannot hold\" shape. It fires only when both hold: the carry is present **and** the
target declares a non-NONE write capability for `electronic.stress`. S1 proved the wiring
against a synthetic stress-expressing target; M40-S2's exporter flip makes the **real** extXYZ
target stress-expressing, so the branch now fires for it with no change to itself (the
capability-driven promise). The end-to-end conversion report is exercised through
`preview_recovery`, which runs the exact recovery prefix of `convert` without exporting; the
full convert/refusal/validation round-trip lives in
``test_stress_convention_roundtrip.py``.
"""

from __future__ import annotations

import io

from tests._dummy_plugins import DummyExporter
from xtalate.capabilities import CapabilityMatrix, Registry
from xtalate.conversion import ConversionEngine
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.schema import CanonicalObject
from xtalate.sdk import CapabilityLevel, FieldCapability, FormatCapabilities

# A single-frame extXYZ carrying a stress channel on the comment line (D18's carry).
_STRESS_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0 0 0 2 0 0 0 3" pbc="T T T"\nH 0 0 0\n'
)

_CARRY_PATH = "user_metadata.custom_per_frame['extxyz:stress']"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def _stress_source() -> CanonicalObject:
    reg = _registry()
    return reg.get_parser("extxyz").parse(io.BytesIO(_STRESS_EXTXYZ), filename="s.extxyz").canonical


def _stress_target_caps() -> FormatCapabilities:
    """Write capabilities of the S1 stand-in stress-expressing target. After M40-S2 flips the
    extXYZ exporter's row, the real extXYZ write declaration carries exactly this shape for
    `electronic.stress` (PARTIAL + the scenario note)."""
    return FormatCapabilities(
        format_id="stress_tgt",
        format_name="Stress Target",
        direction="write",
        fields={
            "atoms.symbols": FieldCapability(level=CapabilityLevel.FULL),
            "atoms.positions": FieldCapability(level=CapabilityLevel.FULL),
            "user_metadata.custom_per_frame": FieldCapability(level=CapabilityLevel.FULL),
            "electronic.stress": FieldCapability(
                level=CapabilityLevel.PARTIAL,
                notes=(
                    "populated only when the stress convention is resolved via "
                    "ambiguous_stress_convention"
                ),
            ),
        },
        max_frames=None,
        required_fields=[],
        native_coordinate_system="cartesian",
    )


def _stress_target_matrix() -> CapabilityMatrix:
    return CapabilityMatrix({("stress_tgt", "write"): _stress_target_caps()})


# --- detection (the new present-but-unmapped-carry shape) -------------------------------


def test_carry_to_stress_expressing_target_emits_the_scenario() -> None:
    from xtalate.conversion.preflight import build_preflight

    diff = build_preflight(_stress_source(), _stress_target_matrix(), "stress_tgt")
    scenarios = [s for s in diff.unresolved if s.scenario == "ambiguous_stress_convention"]
    assert len(scenarios) == 1
    (scenario,) = scenarios
    assert scenario.path == "electronic.stress"
    # The option list is computed at detection time and carried on the scenario (P5) — the one
    # list the engine validates against and the refusal report echoes.
    assert scenario.options == ["ase_sign_convention", "tension_positive"]
    assert scenario.params == {"custom_key": "extxyz:stress"}
    detail = scenario.detail
    assert detail is not None
    assert "extxyz:stress" in detail
    # The carry's fate is the scenario's (retired into `electronic.stress` on resolution), so it
    # is parked in `pending` — the optimistic-preserve convention, like constraints under
    # `constraint_representation` — never predicted preserved-then-silently-retired.
    assert {e.path for e in diff.pending} == {_CARRY_PATH}
    assert _CARRY_PATH not in {e.path for e in diff.preserved}


def test_real_extxyz_target_fires_the_scenario_after_the_s2_flip() -> None:
    # M40-S2 flips the extXYZ write declaration to PARTIAL, so the *real* extXYZ target now
    # expresses stress — the branch is capability-driven and activates with no change to itself
    # (S1's promise). A real extXYZ → extXYZ conversion of a stress-carry source fires the
    # scenario and parks the carry in `pending`; the conversion refuses without a preset (the
    # round-trip suite proves the refusal), so the carry is never silently passed through.
    from xtalate.conversion.preflight import build_preflight

    reg = _registry()
    diff = build_preflight(_stress_source(), reg.capability_matrix(), "extxyz")
    assert any(s.scenario == "ambiguous_stress_convention" for s in diff.unresolved)
    assert {e.path for e in diff.pending} == {_CARRY_PATH}
    assert _CARRY_PATH not in {e.path for e in diff.preserved}


def test_carry_to_a_none_target_is_an_ordinary_carry() -> None:
    # A target that still cannot express stress (every other Phase 1 format) must NOT fire the
    # scenario — the carry is ordinary custom-per-frame data, preserved by the container's FULL
    # capability and round-tripped verbatim by the exporter's fallback (M40-S2, done means #2).
    from xtalate.conversion.preflight import build_preflight

    reg = _registry()
    diff = build_preflight(_stress_source(), reg.capability_matrix(), "poscar")
    assert not any(s.scenario == "ambiguous_stress_convention" for s in diff.unresolved)
    assert _CARRY_PATH not in {e.path for e in diff.pending}


def test_no_carry_to_stress_expressing_target_fires_nothing() -> None:
    from xtalate.conversion.preflight import build_preflight

    reg = _registry()
    source = (
        reg.get_parser("extxyz")
        .parse(
            io.BytesIO(
                b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
                b'pbc="T T T"\nH 0 0 0\n'
            ),
            filename="s.extxyz",
        )
        .canonical
    )
    diff = build_preflight(source, _stress_target_matrix(), "stress_tgt")
    assert not any(s.scenario == "ambiguous_stress_convention" for s in diff.unresolved)
    assert diff.pending == []


# --- conversion wiring (preview_recovery runs convert's exact recovery prefix) -----------


def _conversion_registry() -> Registry:
    reg = _registry()
    reg.register_exporter(DummyExporter("stress_tgt", fields=_stress_target_caps().fields))
    return reg


def test_preview_resolves_the_interpretation_end_to_end() -> None:
    reg = _conversion_registry()
    preview = ConversionEngine(reg).preview_recovery(
        _stress_source(),
        source_format_id="extxyz",
        target_format_id="stress_tgt",
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
    )
    assert preview.unresolved == []
    (assumption,) = preview.assumptions
    assert assumption.scenario == "ambiguous_stress_convention"
    assert assumption.choice == "tension_positive"
    # The Conversion Report states the interpretation in plain language (Revision 1.10 rule) —
    # the preview's description is byte-identical to what convert will record (P4).
    assert "tension-positive per your choice" in assumption.description


def test_preview_without_preset_lists_the_scenario_and_options() -> None:
    reg = _conversion_registry()
    preview = ConversionEngine(reg).preview_recovery(
        _stress_source(),
        source_format_id="extxyz",
        target_format_id="stress_tgt",
    )
    assert preview.assumptions == []
    (unresolved,) = preview.unresolved
    assert unresolved.scenario == "ambiguous_stress_convention"
    assert unresolved.options == ["ase_sign_convention", "tension_positive"]
    assert unresolved.path == "electronic.stress"
