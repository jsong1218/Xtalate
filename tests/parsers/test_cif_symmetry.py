"""Symmetry-operation parsing (M18 deliverable 1, ``parsers/cif/_symmetry.py``).

Expansion itself is not exercised here: this module is the pure string→affine-operation layer,
and its whole contract is that it reads every spelling real files use *exactly*, or refuses.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from xtalate.parsers.cif._symmetry import IDENTITY, parse_symop, parse_symops
from xtalate.sdk import ParseError

F = Fraction


def _row(*values: str | int) -> tuple[Fraction, ...]:
    return tuple(Fraction(v) for v in values)


# --- spellings ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rotation", "translation"),
    [
        ("x,y,z", (_row(1, 0, 0), _row(0, 1, 0), _row(0, 0, 1)), _row(0, 0, 0)),
        ("+x,+y,+z", (_row(1, 0, 0), _row(0, 1, 0), _row(0, 0, 1)), _row(0, 0, 0)),
        ("-x,-y,-z", (_row(-1, 0, 0), _row(0, -1, 0), _row(0, 0, -1)), _row(0, 0, 0)),
        # Spaces, and a translation on one component only.
        ("x, y+1/2, -z", (_row(1, 0, 0), _row(0, 1, 0), _row(0, 0, -1)), _row(0, "1/2", 0)),
        # Leading constant, and a component mixing two variables.
        (
            "1/2-y, x-y, z+1/3",
            (_row(0, -1, 0), _row(1, -1, 0), _row(0, 0, 1)),
            _row("1/2", 0, "1/3"),
        ),
        # Decimal translations mean exactly what the rational spelling means.
        ("x+0.5,y,z", (_row(1, 0, 0), _row(0, 1, 0), _row(0, 0, 1)), _row("1/2", 0, 0)),
        # Quoted, as a CIF value often is.
        ("'-y, x-y, z'", (_row(0, -1, 0), _row(1, -1, 0), _row(0, 0, 1)), _row(0, 0, 0)),
    ],
)
def test_reads_the_spellings_real_files_use(
    text: str, rotation: tuple[tuple[Fraction, ...], ...], translation: tuple[Fraction, ...]
) -> None:
    op = parse_symop(text, line=1)
    assert op.rotation == rotation
    assert op.translation == translation


def test_translations_are_exact_rationals_not_floats() -> None:
    """``1/3`` stays a third, so three applications return exactly to the start.

    With float translations this sum is 0.9999999999999999, which would put a site 1e-16 from
    where it belongs and make the special-position merge compare rounding noise against a
    physical threshold.
    """
    op = parse_symop("x, y, z+1/3", line=1)
    assert op.translation[2] == Fraction(1, 3)
    assert op.translation[2] * 3 == 1


def test_source_spelling_is_preserved_verbatim() -> None:
    """Provenance carries what the file said, not a rendering of what we understood."""
    assert parse_symop("'-y, x-y, z'", line=1).text == "-y, x-y, z"


def test_identity_is_recognised_in_any_spelling() -> None:
    assert parse_symop("x,y,z", line=1).is_identity
    assert parse_symop("+x, +y, +z", line=1).is_identity
    assert IDENTITY.is_identity
    assert not parse_symop("-x,-y,-z", line=1).is_identity


def test_apply_maps_a_coordinate_exactly() -> None:
    op = parse_symop("1/2-x, y+1/2, -z", line=1)
    assert op.apply((F(1, 3), F(1, 4), F(1, 5))) == (F(1, 6), F(3, 4), F(-1, 5))


# --- refusals -------------------------------------------------------------------------------
# Deliverable 1: an operation this parser cannot read is a ParseError, never a skipped
# operation. A dropped operation is a fraction of the physical atoms — silently wrong
# stoichiometry in every downstream conversion.


@pytest.mark.parametrize(
    "text",
    [
        "x, y",  # two components
        "x, y, z, z",  # four components
        "x, , z",  # empty component
        "x, y, w",  # a variable that is not x, y or z
        "x, y, 2**z",  # unreadable term
        "x, y, z/0",  # division by zero
        "x, y, z$",  # stray character
    ],
)
def test_unreadable_operations_raise_rather_than_degrade(text: str) -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_symop(text, line=7)
    (issue,) = excinfo.value.issues
    assert issue.code == "CIF_MALFORMED_SYMOP"
    assert issue.severity == "error"
    assert issue.location == "line 7"


@pytest.mark.parametrize("text", ["2x, y, z", "x, x, z", "x, y, 0"])
def test_non_crystallographic_rotations_are_refused(text: str) -> None:
    """Determinant ±1 is what separates an operation from a typo that parses.

    ``2x,y,z`` reads term-by-term but maps the lattice onto a sublattice; ``x,x,z`` collapses
    two axes. Both would generate sites the crystal does not have, which is the wrong-atom-count
    failure this milestone exists to prevent.
    """
    with pytest.raises(ParseError) as excinfo:
        parse_symop(text, line=1)
    assert excinfo.value.issues[0].code == "CIF_MALFORMED_SYMOP"


def test_an_empty_operation_loop_is_refused() -> None:
    """A file carrying the loop at all must say which operations apply."""
    with pytest.raises(ParseError) as excinfo:
        parse_symops([], line=3)
    assert excinfo.value.issues[0].code == "CIF_MALFORMED_SYMOP"


def test_operation_order_is_preserved() -> None:
    """``parse_notes`` reports multiplicities against the list as the file wrote it."""
    ops = parse_symops(["x,y,z", "-x,-y,-z", "x+1/2,y+1/2,z"], line=1)
    assert [op.text for op in ops] == ["x,y,z", "-x,-y,-z", "x+1/2,y+1/2,z"]
