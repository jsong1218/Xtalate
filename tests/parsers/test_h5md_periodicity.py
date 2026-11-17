"""H5MD box periodicity is never guessed (P3/P4): a box with no usable boundary refuses."""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

from tests.parsers.test_h5md import _minimal_h5md
from xtalate.parsers.h5md import H5MDParser
from xtalate.sdk import ParseError

_EDGES = np.diag([5.0, 6.0, 7.0])


def _buf(boundary: list[bytes] | None) -> BytesIO:
    return _minimal_h5md(
        positions=[np.array([[0.0, 0, 0], [0, 0, 1.0]])],
        species=[np.array([1, 8], dtype=np.int64)],
        box_edges=_EDGES,
        boundary=boundary,
    )


def test_missing_boundary_is_a_recoverable_refusal() -> None:
    with pytest.raises(ParseError) as exc:
        H5MDParser().parse(_buf(None), filename="f.h5md")
    issue = exc.value.issues[0]
    assert issue.code == "H5MD_AMBIGUOUS_PERIODICITY"
    assert issue.recovery_hint == "ambiguous_periodicity"


def test_short_boundary_is_a_recoverable_refusal() -> None:
    with pytest.raises(ParseError) as exc:
        H5MDParser().parse(_buf([b"periodic", b"periodic"]), filename="f.h5md")
    assert exc.value.issues[0].recovery_hint == "ambiguous_periodicity"


def test_declared_boundary_still_parses_unchanged() -> None:
    res = H5MDParser().parse(_buf([b"periodic", b"none", b"periodic"]), filename="f.h5md")
    cell = res.canonical.frames[0].cell
    assert cell is not None
    assert cell.pbc == (True, False, True)


@pytest.mark.parametrize(
    ("choice", "expected"),
    [("periodic", (True, True, True)), ("non_periodic", (False, False, False))],
)
def test_recover_applies_the_explicit_choice(
    choice: str, expected: tuple[bool, bool, bool]
) -> None:
    res = H5MDParser().parse_recover(
        _buf(None),
        filename="f.h5md",
        hint="ambiguous_periodicity",
        choice=choice,
        parameters={},
        recovery_context={"ambiguous_periodicity": {"choice": choice, "parameters": {}}},
    )
    cell = res.canonical.frames[0].cell
    assert cell is not None
    assert cell.pbc == expected
    assert any(i.code == "H5MD_PERIODICITY_SUPPLIED" for i in res.issues)


def test_recover_choice_overrides_a_partially_declared_boundary() -> None:
    """A 2-entry boundary is unusable (never padded); the user's all-axes choice replaces the
    declared entries, and the Assumption text says so (P1)."""
    res = H5MDParser().parse_recover(
        _buf([b"periodic", b"none"]),
        filename="f.h5md",
        hint="ambiguous_periodicity",
        choice="non_periodic",
        parameters={},
        recovery_context={"ambiguous_periodicity": {"choice": "non_periodic", "parameters": {}}},
    )
    cell = res.canonical.frames[0].cell
    assert cell is not None
    assert cell.pbc == (False, False, False)


def test_recover_rejects_an_unknown_choice() -> None:
    with pytest.raises(ValueError):
        H5MDParser().parse_recover(
            _buf(None),
            filename="f.h5md",
            hint="ambiguous_periodicity",
            choice="maybe",
            parameters={},
            recovery_context={"ambiguous_periodicity": {"choice": "maybe", "parameters": {}}},
        )


def test_recover_composes_with_truncation_hint() -> None:
    # A truncate hint arriving while a periodicity choice is already in the context must apply both.
    res = H5MDParser().parse_recover(
        _buf(None),
        filename="f.h5md",
        hint="truncate_at_last_valid_frame",
        choice="truncate",
        parameters={},
        recovery_context={
            "ambiguous_periodicity": {"choice": "periodic", "parameters": {}},
            "truncate_corrupt_tail": {"choice": "truncate", "parameters": {}},
        },
    )
    assert res.canonical.frames[0].cell is not None
