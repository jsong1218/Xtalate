"""Tolerance-profile tests (M5, MASTER_SPEC Part 5 §4)."""

from __future__ import annotations

import pytest

from xtalate.validation._shared import require_supported_precision
from xtalate.validation.tolerance import K_FAIL, K_WARN, Bounds, ToleranceProfile


def _pair(b: Bounds) -> tuple[float, float]:
    return (b.warn, b.fail)


def test_default_profile_matches_the_table() -> None:
    p = ToleranceProfile.named("default")
    assert _pair(p.effective("positions")) == (1e-5, 1e-3)
    assert _pair(p.effective("forces")) == (1e-6, 1e-4)
    assert _pair(p.effective("stress")) == (1e-8, 1e-6)
    assert _pair(p.effective("charges")) == (1e-4, 1e-2)


def test_strict_tightens_and_loose_relaxes_100x() -> None:
    strict = ToleranceProfile.named("strict")
    loose = ToleranceProfile.named("loose")
    assert strict.effective("positions").warn == pytest.approx(1e-7)
    assert loose.effective("positions").warn == pytest.approx(1e-3)


def test_representational_bound_floors_the_threshold() -> None:
    # A bound larger than the base lifts the effective threshold to k × bound (Part 5 §4.2); the
    # floor is never disabled, even under strict.
    p = ToleranceProfile.named("default")
    eff = p.effective("positions", representational_bound=1e-2)
    assert eff.warn == pytest.approx(K_WARN * 1e-2)
    assert eff.fail == pytest.approx(K_FAIL * 1e-2)

    strict = ToleranceProfile.named("strict")
    assert strict.effective("positions", 1e-2).fail == pytest.approx(K_FAIL * 1e-2)


def test_full_precision_bound_is_zero_so_bases_govern() -> None:
    p = ToleranceProfile.named("default")
    assert _pair(p.effective("positions", representational_bound=0.0)) == (1e-5, 1e-3)


def test_unknown_profile_raises_not_silently_defaults() -> None:
    with pytest.raises(ValueError, match="unknown tolerance profile"):
        ToleranceProfile.named("ultra")


def test_as_dict_is_self_contained() -> None:
    d = ToleranceProfile.named("default").as_dict()
    assert d["name"] == "default"
    assert d["positions_warn_ang"] == 1e-5
    assert d["k_warn"] == K_WARN
    assert d["representational_bound_floor"] == "enabled"


# --- Custom tolerance tables (M9, Part 5 §4.4) ---------------------------------------------------


def test_from_mapping_partial_override_inherits_defaults() -> None:
    # Only `forces` is tightened; every omitted quantity keeps the default base.
    p = ToleranceProfile.from_mapping(
        "custom", {"quantities": {"forces": {"warn": 1e-8, "fail": 1e-6}}}
    )
    assert _pair(p.effective("forces")) == (1e-8, 1e-6)
    assert _pair(p.effective("positions")) == (1e-5, 1e-3)  # inherited
    d = p.as_dict()
    assert d["name"] == "custom"
    assert (d["forces_warn"], d["forces_fail"]) == (1e-8, 1e-6)


def test_from_mapping_name_key_overrides_passed_name() -> None:
    p = ToleranceProfile.from_mapping("stem", {"name": "tight", "quantities": {}})
    assert p.name == "tight"


def test_from_mapping_representational_floor_still_applies() -> None:
    # §4.4: the representational-bound floor is never disabled, even for a custom table stricter
    # than the format's precision.
    p = ToleranceProfile.from_mapping(
        "custom", {"quantities": {"positions": {"warn": 1e-12, "fail": 1e-10}}}
    )
    eff = p.effective("positions", representational_bound=1e-2)
    assert eff.fail == pytest.approx(K_FAIL * 1e-2)


@pytest.mark.parametrize(
    ("mapping", "match"),
    [
        ({"quantities": {"bogus": {"warn": 1e-6, "fail": 1e-4}}}, "unknown tolerance quantity"),
        ({"quantities": {"forces": {"warn": 1e-4, "fail": 1e-6}}}, "must not exceed fail"),
        ({"quantities": {"forces": {"warn": -1.0, "fail": 1e-4}}}, "must be non-negative"),
        ({"quantities": {"forces": {"warn": "x", "fail": 1e-4}}}, "must be a number"),
        ({"quantities": {"forces": {"warn": 1e-6}}}, r"exactly \{warn, fail\}"),
        ({"k_warn": 5, "quantities": {}}, "unknown top-level key"),
        ({"quantities": {"pbc": {"warn": 1e-6, "fail": 1e-4}}}, "unknown tolerance quantity"),
    ],
)
def test_from_mapping_rejects_bad_tables_with_actionable_errors(
    mapping: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        ToleranceProfile.from_mapping("custom", mapping)


def test_a_fractional_exporter_declaring_precision_is_refused_not_mis_judged() -> None:
    """Part 5 §4.2's ``x max||L_i||`` scaling is not implemented, so the case must refuse.

    ``_representational_bound`` returns ``0.5*10**-d`` in the field's own units. For a Cartesian
    format that is angstrom and the checks compare angstrom, so it is right; for a fractional
    format the decimals are fractional units and need the lattice scaling to become a distance.
    No Phase 1 exporter declares reduced precision (all write ``repr(float(x))``), so the branch
    has no consumer and building it would be speculative (P6) — but a future fractional exporter
    declaring four-decimal coordinates would otherwise get a tolerance ~|L| times too tight,
    silently. A validation engine that cannot judge a field correctly must say so.
    """
    with pytest.raises(NotImplementedError, match="lattice scaling"):
        require_supported_precision("someformat", {"atoms.positions": 4}, "fractional")


def test_a_cartesian_exporter_declaring_precision_is_supported() -> None:
    # The counter-case: Cartesian decimals are angstrom already, so the unscaled bound is correct
    # and the guard must not fire. Otherwise it would block the case D24 actually built the field
    # for (a low-precision Cartesian writer).
    precision: dict[str, int | None] = {"atoms.positions": 4}
    assert require_supported_precision("someformat", precision, "cartesian") == precision


def test_a_fractional_exporter_with_no_precision_declaration_is_supported() -> None:
    # Every Phase 1 fractional exporter today: full precision, nothing declared, bound 0.0.
    assert require_supported_precision("cif", {}, "fractional") == {}
