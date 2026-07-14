"""Maxwell–Boltzmann physics tests (M8, the roadmap's named risk for this version).

The distribution is correct iff the per-component sample variance equals ``kT/mᵢ`` (in the canonical
Å/fs unit) within statistical tolerance, and the draw is exactly reproducible from its seed. The raw
sample is emitted unchanged — no center-of-mass drift is removed (D43) — so these tests deliberately
do **not** assert zero net momentum; a large-N fixture keeps the variance estimate tight.
"""

from __future__ import annotations

import numpy as np
from ase import units as ase_units

from xtalate.recovery.engine import _maxwell_boltzmann


def _expected_variance(mass_u: float, temperature_k: float) -> float:
    # σ² = kB·T/m in ASE velocity units, scaled to (Å/fs)² by ase.units.fs² (the codebase's factor).
    return float(ase_units.kB * temperature_k / mass_u * ase_units.fs**2)


def test_per_component_variance_matches_kT_over_m() -> None:
    n = 40_000
    temperature_k = 300.0
    masses = np.full(n, 12.011)  # a large single-species fixture for a tight variance estimate.
    v = _maxwell_boltzmann(masses, temperature_k, seed=7)
    assert v.shape == (n, 3)
    measured = v.var(axis=0)  # per Cartesian component
    expected = _expected_variance(12.011, temperature_k)
    # Sample-variance relative error ~ sqrt(2/N) ≈ 0.7 %; 5 % is a safe statistical tolerance.
    np.testing.assert_allclose(measured, expected, rtol=0.05)


def test_variance_scales_inversely_with_mass() -> None:
    n = 40_000
    temperature_k = 500.0
    masses = np.concatenate([np.full(n, 1.008), np.full(n, 15.999)])
    v = _maxwell_boltzmann(masses, temperature_k, seed=3)
    light = v[:n].var()
    heavy = v[n:].var()
    np.testing.assert_allclose(light, _expected_variance(1.008, temperature_k), rtol=0.05)
    np.testing.assert_allclose(heavy, _expected_variance(15.999, temperature_k), rtol=0.05)


def test_same_seed_is_bit_for_bit_deterministic() -> None:
    masses = np.array([12.011, 15.999, 1.008])
    a = _maxwell_boltzmann(masses, 300.0, seed=42)
    b = _maxwell_boltzmann(masses, 300.0, seed=42)
    np.testing.assert_array_equal(a, b)


def test_different_seed_gives_a_different_sample() -> None:
    masses = np.array([12.011, 15.999, 1.008])
    a = _maxwell_boltzmann(masses, 300.0, seed=1)
    b = _maxwell_boltzmann(masses, 300.0, seed=2)
    assert not np.array_equal(a, b)
