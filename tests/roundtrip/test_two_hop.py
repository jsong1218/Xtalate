"""Two-hop round-trips ``A → Canonical → B → Canonical′`` (MASTER_SPEC Part 8 §2.2).

v0.1 proved *identity* round-trips (``test_identity``); this suite adds the cross-format matrix that
catches parser/exporter **asymmetry**. Every ``(source, target)`` pair is enumerated **from the
registry** (a newly registered exporter grows the suite with zero edits — see
``test_matrix_enumeration``), driven through the real Conversion + Validation engines under the
**strict** tolerance profile, with fabricative/selective gaps resolved by fixed recovery presets so
Assumption recording is exercised end to end.

Reusing the Validation Engine (rather than a standalone differ, DECISIONS.md D49) *is* the two-hop
diff: its expected object is Canonical projected to the matrix-computed write plan, and its check
catalog both confirms the comparable subspace survived numerically and asserts every removed path is
absent in the re-parse (``absence_conformance``). The extra assertions here pin the matrix→report
linkage explicitly, so a regression that silently narrowed a capability would fail the suite, not
just the engine.
"""

from __future__ import annotations

import io

import pytest

from tests.roundtrip import _matrix
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.validation import ToleranceProfile

_REGISTRY = default_registry()
_STRICT = ToleranceProfile.named("strict")

# Every (source, target) pair is collected, but only the curated high-risk subset runs on a PR; the
# remainder carries the `nightly` marker and is deselected unless XTALATE_FULL_MATRIX=1 un-gates it
# (tests/conftest.py). A newly registered exporter still auto-enrols in the full nightly matrix
# (P6, test_matrix_enumeration) while the PR gate stays fast and curated (Part 8 §2.4).
_ALL_PAIRS = _matrix.two_hop_pairs(_REGISTRY)
_CURATED = set(_matrix.curated_pr_pairs(_REGISTRY))
_PARAMS = [
    pytest.param(a, b, id=f"{a}_to_{b}", marks=() if (a, b) in _CURATED else pytest.mark.nightly)
    for a, b in _ALL_PAIRS
]


@pytest.mark.parametrize(("source_fmt", "target_fmt"), _PARAMS)
def test_two_hop_roundtrip(source_fmt: str, target_fmt: str) -> None:
    golden = _matrix.golden_source(source_fmt)
    parsed = _REGISTRY.get_parser(source_fmt).parse(io.BytesIO(golden.source), filename=None)
    source = parsed.canonical

    result = ConversionEngine(_REGISTRY).convert(
        source,
        source_format_id=source_fmt,
        target_format_id=target_fmt,
        mode="permissive",
        recovery_choices=_matrix.FIXED_PRESETS,
        tolerance_profile=_STRICT,
    )
    report = result.report

    # A refusal here would mean a fixed preset failed to resolve a gap the four formats can hit —
    # the suite's job is to keep every write-capable pair converting, not to tolerate refusals.
    assert report.status != "refused", f"{source_fmt}→{target_fmt} refused: {report.refusal}"
    assert result.validation is not None
    # Strict profile: the re-parsed B must match the write-plan projection exactly up to declared
    # representation. `passed_with_warnings`/`failed` is a real parser/exporter asymmetry.
    problems = [
        (c.check_id, c.status)
        for c in result.validation.checks
        if c.status not in ("pass", "skipped")
    ]
    assert result.validation.status == "passed", (
        f"{source_fmt}→{target_fmt} validation {result.validation.status}: {problems}"
    )

    # --- Matrix-driven subspace assertions (the M9 cut line, made explicit) ------------------
    matrix = _REGISTRY.capability_matrix()
    preserved = {e.path for e in report.preserved}
    present = source.field_presence().present_paths()

    def _covers(paths: set[str], path: str) -> bool:
        # A `custom_*` container is recorded at per-key granularity (e.g.
        # `custom_per_frame['xyz:comment']`) when the source carries specific keys, so a container
        # path counts as covered if the container itself or any of its keys appears (Part 4 §1).
        return path in paths or any(p.startswith(f"{path}[") for p in paths)

    present_set = set(present)
    for path in _matrix.roundtrippable(matrix, source_fmt, target_fmt):
        # A capability-round-trippable field the source simply does not carry cannot be preserved —
        # restrict the claim to paths actually present in this golden.
        if not _covers(present_set, path):
            continue
        assert _covers(preserved, path), (
            f"{path} is present and FULL-round-trippable {source_fmt}→{target_fmt} but not "
            "reported preserved"
        )

    # Fields outside the intersection (target cannot express them at all) must be routed to
    # `removed` — the matrix→absence linkage of Part 8 §2.2, asserted at test time.
    removed = {e.path for e in report.removed}
    for path in _matrix.unexpressible_source_paths(matrix, present, target_fmt):
        assert path in removed, (
            f"{path} is present in {source_fmt} and inexpressible in {target_fmt} but not "
            "reported removed"
        )
