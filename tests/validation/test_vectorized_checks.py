"""E3: the vectorized ``_check_species`` must equal the original per-atom loop for every shape
of input, and ``_check_positions_rmsd`` is pinned bit-for-bit to its reference arithmetic so a
future "optimisation" cannot move a ulp (P1: validation numbers are truth)."""

from __future__ import annotations

import numpy as np

from tests.validation.test_variable_n_checks import _frame, _provenance, _variable_n_object
from xtalate.schema import AtomsBlock, CanonicalObject, Frame
from xtalate.validation.engine import (
    _check_positions_rmsd,
    _check_species,
    _perm_for,
)
from xtalate.validation.tolerance import ToleranceProfile

_PROFILE = ToleranceProfile.named("default")


def _legacy_species_mismatches(
    expected: CanonicalObject, canonical: CanonicalObject, perm: list[int] | None
) -> int:
    """The pre-E3 loop, verbatim, as the reference oracle."""
    n = min(len(expected.frames), len(canonical.frames))
    mismatches = 0
    for i in range(n):
        exp = expected.frames[i].atoms.symbols
        got = canonical.frames[i].atoms.symbols
        if len(exp) != len(got):
            mismatches += max(len(exp), len(got))
            continue
        fp = _perm_for(perm, len(exp))
        order = fp if fp is not None else list(range(len(exp)))
        mismatches += sum(1 for j in range(len(got)) if exp[order[j]] != got[j])
    return mismatches


def _obj(*frames_symbols: list[str]) -> CanonicalObject:
    return CanonicalObject(
        frames=[_frame(i, s) for i, s in enumerate(frames_symbols)],
        provenance=_provenance(),
    )


def _assert_same_as_legacy(
    expected: CanonicalObject, got: CanonicalObject, perm: list[int] | None
) -> None:
    legacy = _legacy_species_mismatches(expected, got, perm)
    res = _check_species(expected, got, perm)
    assert res.measured["mismatches"] == legacy
    assert (res.status == "pass") == (legacy == 0)


def test_identity_variable_n() -> None:
    o = _variable_n_object()
    _assert_same_as_legacy(o, o, None)


def test_swapped_pair_counts_match_the_loop() -> None:
    expected = _obj(["O", "H", "H"], ["O", "O", "H", "H"])
    got = _obj(["H", "H", "O"], ["O", "O", "H", "H"])
    legacy = _legacy_species_mismatches(expected, got, None)
    assert legacy > 0
    _assert_same_as_legacy(expected, got, None)


def test_permutation_is_applied_like_the_loop() -> None:
    expected = _obj(["O", "H", "H"])
    got = _obj(["H", "H", "O"])
    _assert_same_as_legacy(expected, got, [1, 2, 0])  # maps exactly -> 0 mismatches
    assert _check_species(expected, got, [1, 2, 0]).status == "pass"


def test_permutation_sized_for_another_frame_falls_back_to_identity() -> None:
    expected = _obj(["O", "H", "H"], ["O", "O", "H", "H"])
    _assert_same_as_legacy(expected, expected, [0, 2, 1])  # len-3 map on a len-4 frame


def test_length_mismatch_counts_max_like_the_loop() -> None:
    expected = _obj(["O", "H", "H"])
    got = _obj(["O", "H", "H", "H"])
    _assert_same_as_legacy(expected, got, None)


def test_unequal_frame_counts_compare_the_common_prefix() -> None:
    expected = _obj(["O", "H"], ["O", "H"])
    got = _obj(["O", "H"])
    _assert_same_as_legacy(expected, got, None)


def test_empty_frames() -> None:
    # `_frame` builds a 1-D positions array, which AtomsBlock rejects for zero atoms, so build
    # the empty frames directly with a (0, 3) positions array.
    o = CanonicalObject(
        frames=[
            Frame(index=i, atoms=AtomsBlock(symbols=[], positions=np.zeros((0, 3))))
            for i in range(2)
        ],
        provenance=_provenance(),
    )
    _assert_same_as_legacy(o, o, None)


def test_check_positions_rmsd_arithmetic_is_pinned() -> None:
    expected = _variable_n_object()
    rng = np.random.default_rng(7)
    got = CanonicalObject(
        frames=[
            Frame(
                index=f.index,
                atoms=AtomsBlock(
                    symbols=list(f.atoms.symbols),
                    positions=np.asarray(f.atoms.positions, dtype=float)
                    + rng.normal(scale=1e-3, size=np.asarray(f.atoms.positions).shape),
                ),
            )
            for f in expected.frames
        ],
        provenance=_provenance(),
    )
    res = _check_positions_rmsd(expected, got, None, _PROFILE, {"atoms.positions": None})
    rmsds: list[float] = []
    maxd = 0.0
    for a, b in zip(expected.frames, got.frames, strict=True):
        disp = np.linalg.norm(
            np.asarray(b.atoms.positions, dtype=float) - np.asarray(a.atoms.positions, dtype=float),
            axis=1,
        )
        rmsds.append(float(np.sqrt(np.mean(disp**2))))
        maxd = max(maxd, float(disp.max()))
    # Bit-exact, not approx: the arithmetic must not drift.
    assert res.measured["rmsd_ang"] == max(rmsds)
    assert res.measured["max_displacement_ang"] == maxd
    assert res.measured["frames_compared"] == 2
