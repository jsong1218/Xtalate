"""Tolerance-profile tests (M5, MASTER_SPEC Part 5 §4)."""

from __future__ import annotations

import pytest

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
