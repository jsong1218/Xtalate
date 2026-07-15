"""Report-completeness property test — the single most important test in the repository (M10).

MASTER_SPEC Part 8 §1.2 makes two properties hold over **every** conversion, enforcing **P1** (no
silent loss) and **P4** (no misfiled fabrication):

* **Property 1 — completeness invariant.** Every source-``present``/``mixed`` path appears in
  ``preserved`` ∪ ``removed``; every ``supplied`` entry names a source-``absent`` path traced to a
  recorded Assumption.
* **Property 2 — absence conformance.** Every ``removed`` path is absent in the re-parsed output.

The v0.1-M4 runtime assertion checks conversions that *happen*; this harness checks conversions that
have *not* happened yet. The **stage-1 generator** (``_generators``) systematically nulls/populates
each optional field-path of the worked-example goldens (plus a per-frame ``mixed`` config) and this
suite drives every ``(mutant, target)`` pair through the real Conversion Engine with fixed recovery
presets, asserting both properties (``_properties``) on each report — including refused reports,
which must still satisfy the completeness invariant (Part 4 §2, §3.3).

Stage 2 (hypothesis strategies over randomized objects, with shrinking) is the companion suite
``test_report_completeness_hypothesis`` (D50); this stage-1 sweep merges before it. **Zero waivers
/skips** — a red property is a stop-the-line event, never an ``xfail`` (v0.2 standing rule 3).
"""

from __future__ import annotations

import io

import pytest

from tests.property import _generators, _properties
from tests.roundtrip._matrix import FIXED_PRESETS
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation import ToleranceProfile

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_STRICT = ToleranceProfile.named("strict")
_TARGETS = sorted(e.format_id for e in _REGISTRY.exporters())
_CASES = _generators.mutant_cases()

# (case_id, source_format, object, target) — the full stage-1 lattice × every write-capable target.
_PARAMS = [
    (case_id, source_fmt, obj, target) for case_id, source_fmt, obj in _CASES for target in _TARGETS
]


@pytest.mark.parametrize(
    ("case_id", "source_fmt", "source", "target"),
    _PARAMS,
    ids=[f"{case_id}->{target}" for case_id, _f, _o, target in _PARAMS],
)
def test_report_is_complete(
    case_id: str, source_fmt: str, source: CanonicalObject, target: str
) -> None:
    result = _ENGINE.convert(
        source,
        source_format_id=source_fmt,
        target_format_id=target,
        mode="permissive",
        recovery_choices=FIXED_PRESETS,
        tolerance_profile=_STRICT,
    )
    report = result.report

    # Property 1 holds for *every* terminal report — completed, awaiting_recovery, or refused. A
    # refusal still accounts for every present path and traces every fabrication (Part 4 §2, §3.3).
    p1 = _properties.completeness_violations(source, report)
    assert not p1, f"{case_id}->{target} status={report.status}: completeness violated: {p1}"

    # Property 2 needs the re-parsed output; a refused conversion produces none, so it is
    # inapplicable there (nothing was written to contradict the report).
    if report.status == "refused":
        assert report.refusal is not None
        return
    assert result.output is not None, f"{case_id}->{target}: completed report but no output bytes"
    reparsed = (
        _REGISTRY.get_parser(target).parse(io.BytesIO(result.output), filename=None).canonical
    )
    p2 = _properties.absence_violations(report, reparsed)
    assert not p2, f"{case_id}->{target}: absence conformance violated: {p2}"


def _extxyz_to_xyz() -> tuple[CanonicalObject, ConversionResult]:
    """A real conversion that *removes* fields (extXYZ carries forces/energy/charges the plain XYZ
    target cannot hold) — the fixture the dropped-``removed``-entry tamper test mutates."""
    base = next(o for cid, _f, o in _CASES if cid == "extxyz:base")
    result = _ENGINE.convert(
        base,
        source_format_id="extxyz",
        target_format_id="xyz",
        mode="permissive",
        recovery_choices=FIXED_PRESETS,
        tolerance_profile=_STRICT,
    )
    return base, result


def test_completeness_catches_dropped_removed_entry() -> None:
    """The M10 done-means: a deliberately broken report finalizer (drop one ``removed`` entry) is
    caught by the **property**, not merely by the runtime assertion. Feeding a tampered report to
    the property checker directly proves the check is an independent guard — the runtime assertion
    (which would have raised inside ``convert``) is not in the loop here."""
    source, result = _extxyz_to_xyz()
    report = result.report
    assert report.removed, "fixture must remove at least one field for this test to be meaningful"
    # A clean report passes.
    assert _properties.completeness_violations(source, report) == []

    tampered = report.model_copy(update={"removed": report.removed[1:]})
    dropped = report.removed[0].path
    violations = _properties.completeness_violations(source, tampered)
    assert violations, "dropping a removed entry must be caught as silent loss (P1)"
    assert any(dropped in v for v in violations)


def test_completeness_catches_untraceable_supplied() -> None:
    """The fabrication half of Property 1: a ``supplied`` entry whose Assumption was dropped is
    silent fabrication (**P4**) and must be caught. Uses a conversion that genuinely fabricates
    (any → POSCAR without a lattice runs ``missing_lattice`` recovery)."""
    source = next(o for cid, _f, o in _CASES if cid == "xyz:base")
    result = _ENGINE.convert(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        mode="permissive",
        recovery_choices=FIXED_PRESETS,
        tolerance_profile=_STRICT,
    )
    report = result.report
    assert report.supplied and report.assumptions, "fixture must fabricate for this test"
    assert _properties.completeness_violations(source, report) == []

    tampered = report.model_copy(update={"assumptions": []})
    violations = _properties.completeness_violations(source, tampered)
    assert violations, "a supplied entry with no backing Assumption must be caught (P4)"


def test_stage1_lattice_is_non_vacuous() -> None:
    """Guard against a silently vacuous property suite: the stage-1 lattice must, across its
    ``(mutant, target)`` pairs, actually exercise both properties — some conversions removing
    fields, some fabricating them. A refactor that made every case trivially pass fails here."""
    any_removed = any_supplied = False
    for _cid, fmt, obj in _CASES:
        for target in _TARGETS:
            rep = _ENGINE.convert(
                obj,
                source_format_id=fmt,
                target_format_id=target,
                mode="permissive",
                recovery_choices=FIXED_PRESETS,
                tolerance_profile=_STRICT,
            ).report
            any_removed = any_removed or bool(rep.removed)
            any_supplied = any_supplied or bool(rep.supplied)
            if any_removed and any_supplied:
                return
    assert any_removed, "no conversion removed a field — Property 2 would be vacuous"
    assert any_supplied, (
        "no conversion fabricated a field — Property 1's supplied clause is vacuous"
    )
