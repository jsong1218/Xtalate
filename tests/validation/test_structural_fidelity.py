"""structural_fidelity: occupancies, constraints, space group and image flags are compared."""

from __future__ import annotations

import numpy as np

from tests.validation._structural_helpers import fixed, frame_with, selective
from xtalate.schema import Frame
from xtalate.validation._structural import StructuralTally
from xtalate.validation.report import CheckResult
from xtalate.validation.tolerance import ToleranceProfile

_TOL = ToleranceProfile.named("default")


def _run(
    expected: Frame,
    actual: Frame,
    perm: list[int] | None = None,
    removed: frozenset[str] = frozenset(),
) -> CheckResult | None:
    tally = StructuralTally()
    tally.observe(expected, actual, perm)
    return tally.result(_TOL, 0.0, removed)


def _status(result: CheckResult | None) -> str:
    assert result is not None
    return result.status


def test_returns_none_when_no_structural_field_is_expected() -> None:
    f = frame_with()
    assert _run(f, f) is None


def test_matching_occupancies_pass() -> None:
    assert (
        _status(_run(frame_with(occupancies=[1.0, 0.5]), frame_with(occupancies=[1.0, 0.5])))
        == "pass"
    )


def test_dropped_occupancies_fail() -> None:
    result = _run(frame_with(occupancies=[1.0, 0.5]), frame_with())
    assert _status(result) == "fail"
    assert result is not None and "atoms.occupancies" in result.paths


def test_drifted_occupancies_fail() -> None:
    assert (
        _status(_run(frame_with(occupancies=[1.0, 0.5]), frame_with(occupancies=[1.0, 0.4])))
        == "fail"
    )


def test_unknown_site_occupancy_is_not_filled_in_p3() -> None:
    # expected [1.0, None] (second site unknown) vs actual [1.0, 0.5]: a fabricated value is a
    # mismatch, never "close enough"; and a None on both sides matches.
    assert (
        _status(_run(frame_with(occupancies=[1.0, None]), frame_with(occupancies=[1.0, 0.5])))
        == "fail"
    )
    assert (
        _status(_run(frame_with(occupancies=[1.0, None]), frame_with(occupancies=[1.0, None])))
        == "pass"
    )
    assert (
        _status(_run(frame_with(occupancies=[1.0, 0.5]), frame_with(occupancies=[1.0, None])))
        == "fail"
    )


def test_occupancies_compared_through_the_permutation() -> None:
    e = frame_with(occupancies=[1.0, 0.5])
    a = frame_with(occupancies=[0.5, 1.0])
    assert _status(_run(e, a, perm=[1, 0])) == "pass"
    assert _status(_run(e, a)) == "fail"


def test_selective_dynamics_mask_must_survive() -> None:
    mask = [[True, False, True], [True, True, True]]
    assert (
        _status(
            _run(frame_with(constraints=selective(mask)), frame_with(constraints=selective(mask)))
        )
        == "pass"
    )
    assert _status(_run(frame_with(constraints=selective(mask)), frame_with())) == "fail"


def test_selective_dynamics_mask_is_compared_through_the_permutation() -> None:
    e = frame_with(constraints=selective([[True, False, True], [True, True, True]]))
    a = frame_with(constraints=selective([[True, True, True], [True, False, True]]))
    assert _status(_run(e, a, perm=[1, 0])) == "pass"
    assert _status(_run(e, a)) == "fail"


def test_fixed_atoms_indices_are_compared_through_the_permutation() -> None:
    # Source atom 0 is fixed. Output position 1 holds source atom 0 (perm [1, 0]), so the
    # re-parsed output must list index 1.
    e = frame_with(constraints=fixed([0]))
    assert _status(_run(e, frame_with(constraints=fixed([1])), perm=[1, 0])) == "pass"
    assert _status(_run(e, frame_with(constraints=fixed([0])), perm=[1, 0])) == "fail"
    assert _status(_run(e, frame_with(constraints=fixed([0])))) == "pass"


def test_space_group_must_match_exactly() -> None:
    assert _status(_run(frame_with(space_group="Fm-3m"), frame_with(space_group="Fm-3m"))) == "pass"
    assert _status(_run(frame_with(space_group="Fm-3m"), frame_with(space_group="P1"))) == "fail"
    assert _status(_run(frame_with(space_group="Fm-3m"), frame_with())) == "fail"


def test_image_flags_compared_exactly_through_the_permutation() -> None:
    flags = np.array([[0, 0, 1], [2, 0, 0]])
    e = frame_with(image_flags=flags)
    assert _status(_run(e, frame_with(image_flags=flags[[1, 0]]), perm=[1, 0])) == "pass"
    assert _status(_run(e, frame_with(image_flags=flags + 1))) == "fail"
    assert _status(_run(e, frame_with())) == "fail"


def test_a_disclosed_removal_is_not_failed_again() -> None:
    e = frame_with(space_group="Fm-3m", occupancies=[1.0, 0.5])
    removed = frozenset({"cell.space_group", "atoms.occupancies"})
    # Everything structural was reported removed: nothing left to judge, so no check is emitted.
    assert _run(e, frame_with(), removed=removed) is None
    # Only one of the two is reported removed: the other is still judged (and fails).
    result = _run(e, frame_with(), removed=frozenset({"cell.space_group"}))
    assert _status(result) == "fail"
    assert result is not None and result.paths == ["atoms.occupancies"]


def test_observation_accumulates_across_frames() -> None:
    tally = StructuralTally()
    good = frame_with(space_group="P1")
    tally.observe(good, good, None)
    tally.observe(good, frame_with(space_group="P2"), None)
    assert _status(tally.result(_TOL, 0.0, frozenset())) == "fail"


# --- Malformed (short) arrays fail closed instead of raising (M6, D303) ----------------------


def test_short_image_flags_array_fails_instead_of_raising() -> None:
    flags = np.array([[0, 0, 1], [2, 0, 0]])
    short = frame_with(image_flags=flags)
    # Bypass validation to hand the tally an invalid object: one row of flags for two atoms.
    short = short.model_copy(
        update={"custom_per_atom": {k: v[:1] for k, v in short.custom_per_atom.items()}}
    )
    result = _run(short, frame_with(image_flags=flags), perm=[1, 0])
    assert _status(result) == "fail"


def test_short_selective_dynamics_mask_fails_instead_of_raising() -> None:
    short_mask = [[True, False, True]]  # one row for two atoms
    result = _run(
        frame_with(constraints=selective(short_mask)),
        frame_with(constraints=selective(short_mask)),
        perm=[1, 0],
    )
    assert _status(result) == "fail"


def test_out_of_range_permutation_fails_instead_of_raising() -> None:
    e = frame_with(occupancies=[1.0, 0.5])
    assert _status(_run(e, frame_with(occupancies=[1.0, 0.5]), perm=[0, 7])) == "fail"
