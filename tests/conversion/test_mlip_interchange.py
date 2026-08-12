"""The MLIP interchange proof (M41-S1, MASTER_SPEC Part 8 §3).

A governed golden case proving Xtalate speaks the MLIP training lingua franca *completely*:
a labeled extXYZ carrying **per-frame energy + per-atom forces + stress** round-trips
``extXYZ → Canonical → extXYZ`` with all three first-class, validated and reported. Because
stress is only first-class under a resolved convention (M40), the round-trip runs with the
``ambiguous_stress_convention=tension_positive`` recovery preset — the first governed golden
case whose round-trip is *recovery-resolved* rather than an identity round-trip.

Two properties of the current engine the proof pins:

* **The resolved proof runs materialized-only.** ``convert_stream`` refuses
  ``ambiguous_stress_convention`` by design (it cannot honor a convention choice mid-stream),
  and a supplied preset routes to the materialized ``convert`` anyway — so the streamed/
  materialized comparison is the **no-preset refusal**, asserted *substantive-report-identical*:
  every report field except the human-readable ``refusal.message`` (which legitimately carries
  path-appropriate guidance — the streamed path points the caller at the materialized convert,
  which can honor presets) plus ``output=None`` and ``validation=None``. Each message is pinned
  to its exact string, so the assertion fails loudly if the substantive fields ever diverge or
  either message drifts (M41 done-means #3; the M12 standing rule 3 scoping, Revision 1.40).
* **The tension-positive convention is real, not cosmetic.** The exporter writes stress in the
  compression-positive ASE convention its files carry, so a second pass that re-reads the
  written file under the *same* ``tension_positive`` preset lands on the sign-flipped tensor —
  the M40 teeth (a wrong choice is detectably wrong), stated here at the MLIP level rather than
  asserted away.

The golden case itself (``tests/golden/extxyz/mlip-labeled-2frame/``) is corpus-governed: a
licensed manifest, hash tripwires, and a hand-verified ``expected.canonical.json`` holding the
UNRESOLVED parse (energy/forces first-class, stress as the ``extxyz:stress`` carry) under the
v0.2 governance rules (Part 8 §3).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from ase.stress import voigt_6_to_full_3x3_stress

from tests._format_helpers import assert_matches_golden
from xtalate.conversion import ConversionEngine
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation.tolerance import ToleranceProfile

GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "extxyz" / "mlip-labeled-2frame"
SOURCE_PATH = GOLDEN_DIR / "mlip_labeled.extxyz"
EXPECTED_PATH = GOLDEN_DIR / "expected.canonical.json"

# The deterministic recovery preset the interchange proof round-trips under (M40, Part 4 §3.3).
_PRESET = {"ambiguous_stress_convention": {"choice": "tension_positive"}}

# The two path-appropriate refusal messages, pinned verbatim (M41 done-means #3): the streamed
# path, which cannot honor a recovery choice mid-stream, points the caller at the materialized
# convert, which can — the "(the materialized convert)" guidance is deliberate, not a stray
# fragment (Revision 1.40 scopes standing rule 3 to the *substantive* report content).
_MATERIALIZED_REFUSAL_MESSAGE = (
    "conversion needs recovery decisions that were not supplied; provide them as "
    "recovery_choices presets, or choose a target that does not require the missing fields"
)
_STREAMED_REFUSAL_MESSAGE = (
    "conversion needs recovery decisions that were not supplied; provide them as "
    "recovery_choices presets (the materialized convert), or choose a target that does not "
    "require the missing fields"
)


@pytest.fixture(scope="module")
def engine() -> ConversionEngine:
    return ConversionEngine(default_registry())


@pytest.fixture(scope="module")
def source() -> CanonicalObject:
    return (
        ExtxyzParser()
        .parse(io.BytesIO(SOURCE_PATH.read_bytes()), filename="mlip_labeled.extxyz")
        .canonical
    )


def _stress_fail_bound() -> float:
    return ToleranceProfile.named("default").effective("stress").fail


def _energy_fail_bound() -> float:
    return ToleranceProfile.named("default").effective("energy").fail


def _forces_fail_bound() -> float:
    return ToleranceProfile.named("default").effective("forces").fail


def _carry(obj: CanonicalObject) -> np.ndarray:
    """The per-frame ``extxyz:stress`` carry coerced to float — shape (F, 6) Voigt-6."""
    return np.asarray(obj.user_metadata.custom_per_frame["extxyz:stress"], dtype=float)


def _reparse(output: bytes) -> CanonicalObject:
    return ExtxyzParser().parse(io.BytesIO(output), filename=None).canonical


# --- done means #1 + proof step 1: the governed parse anchor -------------------------


def test_parse_matches_golden(source: CanonicalObject) -> None:
    """The committed fixture parses to the hand-verified expectation, energy/forces first-class
    and stress still a carry (D18) — the unresolved state the recovery proof starts from."""
    assert_matches_golden(source, EXPECTED_PATH.read_text(encoding="utf-8"))
    # The labels in the state the golden pins: energy and forces first-class immediately…
    assert [f.electronic.total_energy for f in source.frames] == [-14.25, -14.31]
    assert source.frames[0].dynamics.forces is not None
    # …and stress deliberately NOT mapped (never interpreted without a declared convention).
    assert source.frames[0].electronic.stress is None
    assert source.frames[1].electronic.stress is None
    assert "extxyz:stress" in source.user_metadata.custom_per_frame


# --- proof steps 2-3: the resolved round-trip, materialized-only ----------------------


def test_resolved_round_trip_all_three_labels_first_class(
    engine: ConversionEngine, source: CanonicalObject
) -> None:
    """Convert extXYZ → extXYZ under the preset: all three labels first-class, the stress
    interpretation recorded as an Assumption with no ``supplied`` (genuine source data, only its
    sign convention resolved), the plain-language interpretation in the report, and the output
    validated within the stress tolerance base + the existing energy/forces tolerances."""
    conv = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices=_PRESET,
        mode="permissive",
    )
    report = conv.report
    assert report.status == "completed"
    assert conv.output is not None and conv.canonical_out is not None
    assert conv.validation is not None and conv.validation.status == "passed"

    # All three labels first-class in the resolved Canonical: energy/forces as parsed, stress
    # populated on every stress-bearing frame, tension-positive as-is (the Voigt-6 carry
    # expanded to the full 3x3 — the non-diagonal fixture genuinely exercises the reordering).
    canonical_out = conv.canonical_out
    for frame, source_carry in zip(canonical_out.frames, _carry(source), strict=True):
        stress = frame.electronic.stress
        assert stress is not None
        assert np.allclose(stress, voigt_6_to_full_3x3_stress(source_carry))
    assert [f.electronic.total_energy for f in canonical_out.frames] == [-14.25, -14.31]
    assert canonical_out.frames[0].dynamics.forces is not None

    # The interpretation is accounted honestly: an Assumption, no fabricated `supplied` value,
    # the carry retired into the resolved field, and the interpretation in plain language.
    assert [(a.scenario, a.choice) for a in report.assumptions] == [
        ("ambiguous_stress_convention", "tension_positive")
    ]
    assert report.supplied == []
    assert any(e.path == "electronic.stress" for e in report.preserved)
    assert any(e.path == "dynamics.forces" for e in report.preserved)
    assert any(e.path == "electronic.total_energy" for e in report.preserved)
    assert any(e.path == "user_metadata.custom_per_frame['extxyz:stress']" for e in report.removed)
    assert any(
        w.code == "STRESS_SIGN_CONVENTION_CHANGED" and w.source == "export" for w in report.warnings
    )
    (assumption,) = report.assumptions
    assert "tension-positive per your choice" in assumption.description

    # The output validates within the tolerance bases — the D151 carried-value comparison
    # executed honestly (compared back in canonical space, not skipped) for all three labels.
    numeric = next(c for c in conv.validation.checks if c.check_id == "numeric_field_fidelity")
    assert numeric.status == "pass"
    for path, bound in (
        ("electronic.stress", _stress_fail_bound()),
        ("electronic.total_energy", _energy_fail_bound()),
        ("dynamics.forces", _forces_fail_bound()),
    ):
        measured = numeric.measured[path]
        assert isinstance(measured, dict)
        assert measured["missing"] is False
        max_diff = measured["max_abs_diff"]
        assert isinstance(max_diff, (int, float))
        assert max_diff <= bound, f"{path} exceeded its fail bound"
    stress_measured = numeric.measured["electronic.stress"]
    assert isinstance(stress_measured, dict)
    assert stress_measured["compared_via_carry"] is True
    assert stress_measured["carry_key"] == "extxyz:stress"


def test_written_extxyz_reparses_and_converts_again(
    engine: ConversionEngine, source: CanonicalObject
) -> None:
    """The written extXYZ carries all three labels and converts again, green within tolerance.

    The written file declares the compression-positive ASE convention (the exporter reverses the
    canonical tensor), so the second pass under the *same* ``tension_positive`` preset lands on
    the sign-flipped canonical tensor — the M40 teeth stated at the MLIP level: the convention is
    the user's recorded choice, and a wrong choice is detectably wrong. Each conversion is
    self-consistent and validates within the stress base; what must not be asserted is that the
    two canonical tensors are equal under mismatched conventions.
    """
    conv1 = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices=_PRESET,
        mode="permissive",
    )
    output1 = conv1.output
    canonical1 = conv1.canonical_out
    assert output1 is not None and canonical1 is not None
    assert conv1.validation is not None and conv1.validation.status == "passed"

    # The written file carries all three labels: energy and forces first-class, stress as the
    # carry again (the parser never maps it without a declared convention — D18).
    reparsed = _reparse(output1)
    assert [f.electronic.total_energy for f in reparsed.frames] == [-14.25, -14.31]
    assert reparsed.frames[0].dynamics.forces is not None
    assert "extxyz:stress" in reparsed.user_metadata.custom_per_frame
    # The written carry is the canonical tensor reversed to the exporter's ASE convention.
    carried = _carry(reparsed)
    for i, frame in enumerate(canonical1.frames):
        assert np.allclose(
            voigt_6_to_full_3x3_stress(carried[i]), -np.asarray(frame.electronic.stress)
        )

    # Re-parsed and converted again: completes and validates green within the bases.
    conv2 = engine.convert(
        reparsed,
        source_format_id="extxyz",
        target_format_id="extxyz",
        recovery_choices=_PRESET,
        mode="permissive",
    )
    canonical2 = conv2.canonical_out
    assert conv2.report.status == "completed"
    assert conv2.validation is not None and conv2.validation.status == "passed"
    assert canonical2 is not None

    # Teeth: reading the ASE-convention output under tension-positive is detectably sign-flipped
    # (a wrong interpretation is a wrong tensor), and the flip is the *only* difference — the
    # magnitudes sit well inside the stress base after the reversal.
    bound = _stress_fail_bound()
    for i in range(source.frame_count):
        assert np.allclose(
            np.asarray(canonical2.frames[i].electronic.stress),
            -np.asarray(canonical1.frames[i].electronic.stress),
            atol=bound,
            rtol=0.0,
        )
    assert (
        np.abs(
            np.asarray(canonical2.frames[0].electronic.stress)
            + np.asarray(canonical1.frames[0].electronic.stress)
        ).max()
        <= bound
    )


# --- done means #3: the no-preset refusal, substantive-report-identical -----------------


def test_no_preset_materialized_refusal(engine: ConversionEngine, source: CanonicalObject) -> None:
    """Without the preset the materialized path refuses — never a silent interpretation (P4),
    with the path-appropriate message pinned verbatim."""
    conv = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        mode="permissive",
    )
    report = conv.report
    assert report.status == "refused"
    assert conv.output is None and conv.canonical_out is None and conv.validation is None
    assert report.refusal is not None
    assert report.refusal["code"] == "RECOVERY_REQUIRED"
    assert [s["scenario"] for s in report.refusal["unresolved_scenarios"]] == [
        "ambiguous_stress_convention"
    ]
    assert report.assumptions == []
    assert report.refusal["message"] == _MATERIALIZED_REFUSAL_MESSAGE


def _substantive_report(report: Any) -> tuple[dict[str, Any], str]:
    """The report's substantive content (report id / created_at are per-run bookkeeping,
    normalised away per the standing-rule-3 comparison convention) plus the refusal message,
    separated so the cross-path comparison covers every substantive field while each message is
    pinned to its own path-appropriate string."""
    dumped: dict[str, Any] = json.loads(report.model_dump_json())
    dumped["report_id"] = "X"
    dumped["created_at"] = "X"
    refusal = dumped["refusal"]
    assert refusal is not None
    message = str(refusal.pop("message"))
    return dumped, message


def test_no_preset_streamed_refusal_is_substantively_identical_to_materialized(
    engine: ConversionEngine, source: CanonicalObject
) -> None:
    """The cross-path invariant asserted on the no-preset refusal (M41 done-means #3).

    ``convert_stream`` cannot honor a recovery choice mid-stream, so on the stress-carrying
    fixture both paths refuse — and every *substantive* report field is identical between them:
    status, refusal code, unresolved scenarios, preserved/removed/warnings, and no output / no
    validation. ``refusal.message`` legitimately differs by path and is pinned to each correct
    string. The assertion fails loudly if the substantive fields ever diverge or if either
    message drifts from its pinned string (Revision 1.40 scopes the M12 standing rule 3 to the
    substantive report content; no literal byte-identity is asserted, no engine edit).
    """
    materialized = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="extxyz",
        source_filename="mlip_labeled.extxyz",
        mode="permissive",
    )
    output = io.BytesIO()
    streamed = engine.convert_stream(
        io.BytesIO(SOURCE_PATH.read_bytes()),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=output,
        source_filename="mlip_labeled.extxyz",
    )

    mat_dump, mat_message = _substantive_report(materialized.report)
    str_dump, str_message = _substantive_report(streamed.report)
    assert mat_dump == str_dump, "streamed and materialized refusal reports diverged"
    # The one legitimate divergence is the message, and it is the *right* divergence: the
    # streamed path points the caller at the materialized convert, which can honor presets.
    assert mat_message == _MATERIALIZED_REFUSAL_MESSAGE
    assert str_message == _STREAMED_REFUSAL_MESSAGE
    assert mat_message != str_message

    # Both refuse with nothing produced — never a half-written output masquerading as a result.
    assert materialized.output is None and materialized.validation is None
    assert streamed.output is None and streamed.validation is None
    assert output.getvalue() == b""
