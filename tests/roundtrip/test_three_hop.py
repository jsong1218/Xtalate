"""Three-hop return round-trips ``A → B → A`` (MASTER_SPEC Part 8 §2.3).

The symmetric-bug catcher. A bug replicated in *both* B's parser and exporter survives B's own
identity round-trip (Part 5 §5's stated blind spot); it is caught here only because format A's
implementations are independently anchored by golden files (§3). So each case starts from a golden
*expected* Canonical Object (asserted to match its committed `expected.canonical.json`, the external
truth), makes the ``A → B → A`` trip, and diffs the returned object against that anchor over the
matrix-computed comparable subspace under the **strict** tolerance profile.

The pair list is curated to the high-risk set of Part 8 §2.4 — ``xyz↔extxyz`` (near-superset),
``poscar↔extxyz`` (fractional↔Cartesian), ``poscar↔contcar`` (near-identical) — chosen so no leg
needs frame reduction or lattice fabrication; the golden anchor therefore stays exact. Recovery-
exercising and inexpressible-field pairs are the two-hop suite's job (``test_two_hop``).
"""

from __future__ import annotations

import io

import pytest

from tests._format_helpers import assert_matches_golden
from tests.roundtrip import _compare, _matrix
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation import ToleranceProfile

_REGISTRY = default_registry()
_STRICT = ToleranceProfile.named("strict")

# High-risk pairs (Part 8 §2.4), as unordered pairs; each is exercised in both directions below.
_PAIRS: list[tuple[str, str]] = [
    ("xyz", "extxyz"),
    ("poscar", "extxyz"),
    ("poscar", "contcar"),
]
# Exercise each unordered pair in both directions, but only starting from a format that has a golden
# source fixture (the anchor). `contcar` is a target-only format (no golden source, Part 3 §6.1), so
# `poscar↔contcar` runs as `poscar → contcar → poscar` only.
_WITH_GOLDEN = set(_matrix.source_formats_with_golden())
_DIRECTED = [
    (x, y)
    for a, b in _PAIRS
    for x, y in ((a, b), (b, a))
    if x in _WITH_GOLDEN
]


def _convert(source: CanonicalObject, src_fmt: str, tgt_fmt: str) -> bytes:
    result = ConversionEngine(_REGISTRY).convert(
        source,
        source_format_id=src_fmt,
        target_format_id=tgt_fmt,
        mode="permissive",
        recovery_choices=_matrix.FIXED_PRESETS,
        tolerance_profile=_STRICT,
    )
    assert result.report.status != "refused", (
        f"{src_fmt}→{tgt_fmt} refused: {result.report.refusal}"
    )
    assert result.validation is not None and result.validation.status == "passed", (
        f"{src_fmt}→{tgt_fmt} validation "
        f"{result.validation.status if result.validation else 'missing'}"
    )
    assert result.output is not None
    return result.output


@pytest.mark.parametrize(
    ("a", "b"),
    _DIRECTED,
    ids=[f"{a}_via_{b}" for a, b in _DIRECTED],
)
def test_three_hop_return(a: str, b: str) -> None:
    golden = _matrix.golden_source(a)
    canonical = _REGISTRY.get_parser(a).parse(
        io.BytesIO(golden.source), filename=golden.filename
    ).canonical
    # The external-truth anchor: A's parse must match its hand-verified expected object, so a
    # symmetric bug in B cannot be excused by an equally-wrong A implementation (Part 8 §2.3, §3).
    assert_matches_golden(canonical, golden.expected_json)

    b_bytes = _convert(canonical, a, b)
    intermediate = _REGISTRY.get_parser(b).parse(io.BytesIO(b_bytes), filename=None).canonical
    a_bytes = _convert(intermediate, b, a)
    returned = _REGISTRY.get_parser(a).parse(io.BytesIO(a_bytes), filename=None).canonical

    subspace = _matrix.comparable_subspace(_REGISTRY.capability_matrix(), a, b)
    assert subspace, f"empty comparable subspace for {a}↔{b} — the pair proves nothing"
    _compare.assert_equal_over_subspace(canonical, returned, subspace, _STRICT)
