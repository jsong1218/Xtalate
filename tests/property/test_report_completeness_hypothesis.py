"""Report-completeness property test — stage 2: hypothesis over randomized objects (M10).

The same two properties as stage 1 (``test_report_completeness``), driven over **randomized**
Canonical Objects (``_strategies.canonical_objects``) rather than the deterministic golden-mutation
lattice. Independent presence draws across every category at once exercise field-*combinations* and
multi-field ``mixed`` configurations the one-at-a-time sweep cannot, and hypothesis shrinks any
failure to a minimal reproducer (DECISIONS.md D50).

Both properties are re-derived in ``_properties`` (not imported from the runtime guard), exactly as
in stage 1, so this suite is an *independent* generalization of the M4 runtime assertion. **Zero
waivers/skips** — a red property is stop-the-line, never an ``xfail`` (v0.2 standing rule 3).

The example budget is not hard-coded here: it comes from the loaded hypothesis profile
(``tests/conftest.py``), ``pr`` by default (bounded to keep the PR suite under the Part 8 §5
ten-minute cap) and ``nightly`` (the widened search) when ``HYPOTHESIS_PROFILE=nightly`` — the M15B
realization of the extended-budget note (M15C wires it into the nightly workflow).
"""

from __future__ import annotations

import io

from hypothesis import given

from tests.property import _properties, _strategies
from tests.roundtrip._matrix import FIXED_PRESETS
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation import ToleranceProfile

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_STRICT = ToleranceProfile.named("strict")
_TARGETS = sorted(e.format_id for e in _REGISTRY.exporters())

# The round-trip matrix presets plus `constraint_representation=drop_all`: a randomized object may
# carry constraints, which a PARTIAL-capability target (POSCAR selective dynamics) routes through
# recovery (M7). `drop_all` resolves it deterministically so those objects reach a completed report
# instead of refusing — an unused preset is ignored, so this is a harmless superset of the presets.
_PRESETS = {**FIXED_PRESETS, "constraint_representation": {"choice": "drop_all", "parameters": {}}}


@given(source=_strategies.canonical_objects())
def test_report_is_complete_over_random_objects(source: CanonicalObject) -> None:
    # The source format is fixed to `extxyz` deliberately, not swept. The completeness invariant is
    # a function of the *object's* presence map against the target's write capability; the source id
    # only labels the object's origin in the report. extXYZ is the near-superset read format (the
    # widest FULL read surface of the four), so pinning it lets a randomized object carry *any*
    # field-combination without a narrow source capability masking paths — maximizing what each
    # property must account for. Sweeping the source id would add cost without widening coverage.
    for target in _TARGETS:
        result = _ENGINE.convert(
            source,
            source_format_id="extxyz",
            target_format_id=target,
            mode="permissive",
            recovery_choices=_PRESETS,
            tolerance_profile=_STRICT,
        )
        report = result.report

        # Property 1 — completeness invariant — holds for every terminal report, refusals included.
        p1 = _properties.completeness_violations(source, report)
        assert not p1, f"->{target} status={report.status}: completeness violated: {p1}"

        # Property 2 — absence conformance — needs the re-parsed output; a refusal produces none.
        if report.status == "refused":
            assert report.refusal is not None
            continue
        assert result.output is not None, f"->{target}: completed report but no output bytes"
        reparsed = (
            _REGISTRY.get_parser(target).parse(io.BytesIO(result.output), filename=None).canonical
        )
        p2 = _properties.absence_violations(report, reparsed)
        assert not p2, f"->{target}: absence conformance violated: {p2}"
