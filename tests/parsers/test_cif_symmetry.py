"""Symmetry-operation parsing and expansion (M18 deliverables 1–2, ``parsers/cif/_symmetry.py``).

Two contracts, tested in two halves. The parser reads every spelling real files use *exactly*
or refuses outright; the expander applies what was read, merging the coincident images a site on
a symmetry element produces, and never merging anything else.

These tests work in fractional coordinates against a chosen lattice, which is why they can pin
exact rationals. The reader-level behaviour — the same expansion seen through a whole CIF — is
in ``test_cif.py``.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from xtalate.parsers.cif._symmetry import (
    IDENTITY,
    Expansion,
    expand_sites,
    parse_symop,
    parse_symops,
)
from xtalate.sdk import ParseError

F = Fraction

# A 10 Å cube: fractional differences map to ångström by a factor of 10, so every distance in
# the expansion tests below is readable straight off the coordinates.
CUBE = ((10.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 0.0, 10.0))


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


def test_an_operation_loop_without_the_identity_is_refused() -> None:
    """Every symmetry group contains ``x,y,z``; a list omitting it moves every declared site."""
    with pytest.raises(ParseError) as excinfo:
        parse_symops(["-x,-y,-z", "x+1/2,y+1/2,z"], line=4)
    assert excinfo.value.issues[0].code == "CIF_MALFORMED_SYMOP"


# --- expansion ------------------------------------------------------------------------------


def _expand(
    sites: list[tuple[str, str, str]],
    ops: list[str],
    lattice: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ] = CUBE,
) -> Expansion:
    coordinates = [(F(a), F(b), F(c)) for a, b, c in sites]
    return expand_sites(coordinates, parse_symops(ops, line=1), lattice=lattice)


def test_a_general_position_gains_one_atom_per_operation() -> None:
    result = _expand([("1/8", "1/5", "1/7")], ["x,y,z", "-x,-y,-z", "y,x,z", "-y,-x,-z"])
    assert result.multiplicity == (4,)
    assert result.merged == 0
    assert len(result.coordinates) == 4


def test_a_site_on_a_symmetry_element_has_multiplicity_below_the_operation_count() -> None:
    """The origin is fixed by inversion, so four operations produce fewer than four atoms."""
    result = _expand([("0", "0", "0")], ["x,y,z", "-x,-y,-z", "y,x,z", "-y,-x,-z"])
    assert result.multiplicity == (1,)
    assert result.merged == 3


def test_generated_coordinates_are_wrapped_but_declared_ones_are_not() -> None:
    """Wrapping is construction, not laundering of source data (DECISIONS.md D67 rule 3).

    A declared coordinate is a source fact and survives verbatim even at 1.25; a coordinate this
    module *built* by applying an operation has no source spelling to be faithful to, so placing
    it inside the unit cell is part of constructing it.
    """
    result = _expand([("1/4", "1/4", "5/4")], ["x,y,z", "-x,-y,-z"])
    assert result.coordinates[0] == (F(1, 4), F(1, 4), F(5, 4))
    assert result.coordinates[1] == (F(3, 4), F(3, 4), F(3, 4))


def test_images_a_lattice_translation_apart_are_one_atom() -> None:
    """0.999 and 0.001 differ by a lattice vector, not a distance — the minimum-image rule."""
    result = _expand([("0", "0", "1/1000")], ["x,y,z", "x,y,-z"])
    assert result.multiplicity == (1,)


def test_coincidence_is_judged_in_angstrom_not_in_fractional_units() -> None:
    """The same fractional gap merges in a small cell and survives in a large one.

    This is why the threshold is physical (D67 rule 1): 0.004 fractional is 0.004 Å in a 1 Å
    cell — the same atom, rounded — and 0.4 Å in a 100 Å cell, which is a real separation.
    """
    ops = ["x,y,z", "x,y,-z"]
    tiny = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    huge = ((100.0, 0.0, 0.0), (0.0, 100.0, 0.0), (0.0, 0.0, 100.0))
    assert _expand([("0", "0", "1/500")], ops, tiny).multiplicity == (1,)
    assert _expand([("0", "0", "1/500")], ops, huge).multiplicity == (2,)


def test_coincident_images_of_different_sites_are_never_merged() -> None:
    """Two sites sharing a position are partial occupancy — source data, not a special position.

    Merging them would delete an atom the file explicitly declared and change the occupancy sum
    (D67 rule 2), so both survive expansion despite lying at the same place.
    """
    result = _expand([("1/4", "1/4", "1/4"), ("1/4", "1/4", "1/4")], ["x,y,z"])
    assert result.multiplicity == (1, 1)
    assert result.source_index == (0, 1)


def test_source_index_maps_every_atom_back_to_the_site_that_generated_it() -> None:
    """What lets the builder replicate occupancy and labels onto the atoms they describe."""
    result = _expand([("1/8", "1/5", "1/7"), ("0", "0", "0")], ["x,y,z", "-x,-y,-z"])
    assert result.source_index == (0, 0, 1)
    assert result.multiplicity == (2, 1)


def test_the_expansion_arithmetic_is_checkable_from_the_reported_counts() -> None:
    """sites × operations − merged = atoms — the arithmetic the provenance note lets a reader
    check against the source, without re-deriving the expansion."""
    sites = [("1/8", "1/5", "1/7"), ("0", "0", "0"), ("1/2", "0", "0")]
    ops = ["x,y,z", "-x,-y,-z", "y,x,z", "-y,-x,-z"]
    result = _expand(sites, ops)
    assert len(sites) * len(ops) - result.merged == len(result.coordinates)
    assert sum(result.multiplicity) == len(result.coordinates)
