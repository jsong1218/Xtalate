"""extXYZ stress round-trip through the Conversion Engine (M40-S2, Part 4, Part 5).

After S2 a resolved extXYZ stress channel round-trips **extXYZ → Canonical → extXYZ** as a
first-class field: the exporter writes from `electronic.stress` (reversed to the ASE convention)
with a `STRESS_SIGN_CONVENTION_CHANGED` warning in the Conversion Report, and the value validates
within the stress tolerance base — the numeric-fidelity check compares the re-parsed carry back
in canonical space (D151), never false-failing on "missing". An unresolved object refuses
(`RECOVERY_REQUIRED` — an undeclared convention is never interpreted), and the streaming path
refuses identically (standing rule 3: streamed and materialized reports never diverge).
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from ase.stress import voigt_6_to_full_3x3_stress

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.schema import CanonicalObject
from xtalate.validation.tolerance import ToleranceProfile

# A single-frame extXYZ carrying a non-diagonal 3×3 stress (Voigt-6 (xx,yy,zz,yz,xz,xy) after
# ASE's read normalization — the non-diagonal components genuinely exercise the reordering).
_STRESS_EXTXYZ = (
    b'1\nLattice="3 0 0 0 3 0 0 0 3" Properties=species:S:1:pos:R:3 '
    b'stress="1 0.5 0.25 0.5 2 0.75 0.25 0.75 3" pbc="T T T"\nH 0 0 0\n'
)


@pytest.fixture(scope="module")
def registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


@pytest.fixture(scope="module")
def engine(registry: Registry) -> ConversionEngine:
    return ConversionEngine(registry)


def _source(registry: Registry) -> CanonicalObject:
    return (
        registry.get_parser("extxyz")
        .parse(io.BytesIO(_STRESS_EXTXYZ), filename="s.extxyz")
        .canonical
    )


def _stress_fail_bound() -> float:
    return ToleranceProfile.named("default").effective("stress").fail


def _carry(obj: CanonicalObject) -> np.ndarray:
    """The whole per-frame carry coerced to float (shape (F, 6) for the Voigt-6 stress the parser
    records) — the JsonValue union normalized at the boundary so the tests read it as an array."""
    return np.asarray(obj.user_metadata.custom_per_frame["extxyz:stress"], dtype=float)


# --- done means #1: the resolved round-trip is first-class, warned, validated -------------


def test_resolved_round_trip_warns_and_validates(
    engine: ConversionEngine, registry: Registry
) -> None:
    source = _source(registry)
    conv = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices={"ambiguous_stress_convention": {"choice": "ase_sign_convention"}},
        mode="permissive",
    )
    report = conv.report
    # A completed conversion that wrote the field, warned about the transformation, and validated.
    assert report.status == "completed"
    assert conv.output is not None and conv.validation is not None
    assert conv.validation.status == "passed"
    # The report accounts the interpretation honestly: the field preserved (interpreted, not
    # fabricated — no `supplied` entry), the carry retired, the assumption recorded.
    assert any(e.path == "electronic.stress" for e in report.preserved)
    assert any(e.path == "user_metadata.custom_per_frame['extxyz:stress']" for e in report.removed)
    assert report.supplied == []
    assert [(a.scenario, a.choice) for a in report.assumptions] == [
        ("ambiguous_stress_convention", "ase_sign_convention")
    ]
    # The exporter's sign reversal is in the report with the stable code (Part 2 §3.7.1), sourced
    # from the exporter — this is the first time the contract fires for a real populated field.
    assert any(
        w.code == "STRESS_SIGN_CONVENTION_CHANGED" and w.source == "export" for w in report.warnings
    )
    # The numeric-fidelity check compared the re-parsed carry back in canonical space (D151) —
    # the post-conversion diff passed within the stress tolerance base, not by skipping.
    numeric = next(c for c in conv.validation.checks if c.check_id == "numeric_field_fidelity")
    assert numeric.status == "pass"
    measured = numeric.measured["electronic.stress"]
    assert isinstance(measured, dict)
    assert measured["compared_via_carry"] is True
    assert measured["carry_key"] == "extxyz:stress"
    assert measured["missing"] is False
    max_diff = measured["max_abs_diff"]
    assert isinstance(max_diff, (int, float))
    assert max_diff <= _stress_fail_bound()
    # The output's carry holds the exporter's declared convention (ASE): the negated canonical,
    # Voigt-compressed (expanded back here via ASE's inverse for the comparison).
    output = conv.output
    canonical_out = conv.canonical_out
    assert output is not None and canonical_out is not None
    reparsed = registry.get_parser("extxyz").parse(io.BytesIO(output), filename=None).canonical
    canonical = np.asarray(canonical_out.frames[0].electronic.stress)
    carried = _carry(reparsed)[0]
    assert np.allclose(voigt_6_to_full_3x3_stress(carried), -canonical)


def test_value_validated_within_the_stress_tolerance_base(
    engine: ConversionEngine, registry: Registry
) -> None:
    # The round-trip VALUE is validated within the new tolerance base: resolve pass 1, write,
    # re-parse, resolve pass 2 with the consistent choice, and the two canonical tensors agree
    # within the stress base (the D25-precedent per-quantity base, Part 5 §4.3).
    source = _source(registry)
    conv1 = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices={"ambiguous_stress_convention": {"choice": "ase_sign_convention"}},
        mode="permissive",
    )
    output1 = conv1.output
    canonical1 = conv1.canonical_out
    assert output1 is not None and canonical1 is not None
    reparsed = registry.get_parser("extxyz").parse(io.BytesIO(output1), filename=None).canonical
    conv2 = engine.convert(
        reparsed,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices={"ambiguous_stress_convention": {"choice": "ase_sign_convention"}},
        mode="permissive",
    )
    canonical2_out = conv2.canonical_out
    assert canonical2_out is not None
    first = np.asarray(canonical1.frames[0].electronic.stress)
    second = np.asarray(canonical2_out.frames[0].electronic.stress)
    bound = _stress_fail_bound()
    assert np.allclose(first, second, atol=bound, rtol=0.0)
    # Exact for a full-precision round-trip — well inside the base (the teeth: a sign mistake
    # would be ~2×|tensor|, orders of magnitude over the bound).
    assert np.abs(first - second).max() <= bound


def test_tension_positive_choice_also_round_trips(
    engine: ConversionEngine, registry: Registry
) -> None:
    source = _source(registry)
    conv = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices={"ambiguous_stress_convention": {"choice": "tension_positive"}},
        mode="permissive",
    )
    assert conv.report.status == "completed"
    assert conv.validation is not None and conv.validation.status == "passed"
    canonical_out = conv.canonical_out
    assert canonical_out is not None
    # Tension-positive resolution: canonical equals the source tensor as-is (no sign flip on read;
    # the source carry is Voigt-6, expanded here via ASE's inverse for the comparison), and the
    # exporter still reverses on write (ASE convention) with the warning.
    source_carry = _carry(source)[0]
    assert np.allclose(
        np.asarray(canonical_out.frames[0].electronic.stress),
        voigt_6_to_full_3x3_stress(source_carry),
    )
    assert any(
        w.code == "STRESS_SIGN_CONVENTION_CHANGED" and w.source == "export"
        for w in conv.report.warnings
    )


# --- done means #2: an unresolved object refuses — never a silent pass-through -------------


def test_unresolved_conversion_refuses(engine: ConversionEngine, registry: Registry) -> None:
    conv = engine.convert(
        _source(registry),
        source_format_id="extxyz",
        target_format_id="extxyz",
        mode="permissive",
    )
    assert conv.report.status == "refused"
    assert conv.output is None and conv.canonical_out is None and conv.validation is None
    assert conv.report.refusal is not None
    assert conv.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = [s["scenario"] for s in conv.report.refusal["unresolved_scenarios"]]
    assert scenarios == ["ambiguous_stress_convention"]
    # No assumption was recorded and nothing was silently interpreted (P4).
    assert conv.report.assumptions == []


def test_strict_mode_refuses_unacknowledged_without_choices(
    engine: ConversionEngine, registry: Registry
) -> None:
    # Strict mode with no choices refuses for the same unresolved reason; supplying the preset
    # resolves it (the interpretation is the user's decision, never a default).
    conv = engine.convert(
        _source(registry),
        source_format_id="extxyz",
        target_format_id="extxyz",
        mode="strict",
    )
    assert conv.report.status == "refused"
    assert conv.report.refusal is not None
    assert conv.report.refusal["code"] == "RECOVERY_REQUIRED"


# --- the streaming path refuses identically (standing rule 3) ----------------------------


def test_convert_stream_refuses_a_stress_carry_without_partial_output(
    engine: ConversionEngine,
) -> None:
    assert engine.streaming_eligible("extxyz", "extxyz")  # the pair is streaming-eligible…
    out = io.BytesIO()
    conv = engine.convert_stream(
        io.BytesIO(_STRESS_EXTXYZ),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=out,
    )
    # …yet the data fires `ambiguous_stress_convention` mid-stream, and the stream refuses
    # exactly as the materialized convert does — no silent pass-through of an undeclared sign
    # convention (M40), and no half-written output masquerading as a completed conversion.
    assert conv.report.status == "refused"
    assert conv.report.refusal is not None
    assert conv.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = [s["scenario"] for s in conv.report.refusal["unresolved_scenarios"]]
    assert scenarios == ["ambiguous_stress_convention"]
    assert conv.report.assumptions == []
    assert out.getvalue() == b""  # the partial write was discarded (M12 deliverable 5)
