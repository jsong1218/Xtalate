"""Coordinate-column semantics for LAMMPS dumps (M46; the shared `_lammps` core).

A dump's ``ITEM: ATOMS`` header names its per-atom columns, and which three-name family
is present decides how the coordinates are interpreted before conversion to canonical
Cartesian Å (Part 2 §3.4). LAMMPS's coordinate-column vocabulary is fixed:

* ``x``/``y``/``z`` — wrapped Cartesian, in the box frame (already Cartesian; the
  parser subtracts the box origin).
* ``xs``/``ys``/``zs`` — scaled, i.e. fractional in the tilted box (→ multiply by the
  lattice; :func:`xtalate.parsers._lammps.box.scaled_to_cartesian`).
* ``xu``/``yu``/``zu`` — unwrapped Cartesian, in the box frame (continuous across
  periodic images; Cartesian directly).

The interpretation is **deterministic from the column names** — the resolver never
guesses. Exactly one family must be complete: none present means the dump carries no
coordinates the parser can map (refused), and more than one complete family means the
file is ambiguous about which reading is authoritative (refused — never a silent
preference). The chosen interpretation is recorded in ``parse_notes`` so the report
states it (S3 states it *alongside* the image-flag warning, because the two facts are
only useful together).

Image flags (``ix``/``iy``/``iz``) are deliberately **not** resolved here: applying them
would unwrap the coordinates — an unrequested transform (DECISIONS.md D43) — and M46-S3
carries them specifically to ``custom_per_atom`` instead, never applying them on parse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class CoordinateKind(StrEnum):
    """The three LAMMPS coordinate spellings, keyed to their canonical interpretation."""

    CARTESIAN = "cartesian"  # x/y/z — wrapped, box frame.
    SCALED = "scaled"  # xs/ys/zs — fractional in the tilted box.
    UNWRAPPED = "unwrapped"  # xu/yu/zu — continuous Cartesian, box frame.


_FAMILIES: dict[CoordinateKind, tuple[str, str, str]] = {
    CoordinateKind.CARTESIAN: ("x", "y", "z"),
    CoordinateKind.SCALED: ("xs", "ys", "zs"),
    CoordinateKind.UNWRAPPED: ("xu", "yu", "zu"),
}

#: Every coordinate column name across all three families — the single authoritative set a
#: parser consults to decide which header names it has already claimed as coordinates (so it
#: does not re-declare the family map; the dump parser builds its ``_KNOWN_COLUMNS`` from this).
COORDINATE_COLUMN_NAMES: frozenset[str] = frozenset(
    name for family in _FAMILIES.values() for name in family
)


@dataclass(frozen=True)
class CoordinateColumns:
    """The resolved coordinate family of an ``ITEM: ATOMS`` header.

    ``columns`` is the actual three header names in order (``("x", "y", "z")`` or
    ``("xs", "ys", "zs")`` or ``("xu", "yu", "zu")``), so the parser reads values by
    name without assuming a fixed column order.
    """

    kind: CoordinateKind
    columns: tuple[str, str, str]


def resolve_coordinate_columns(columns: Sequence[str]) -> CoordinateColumns:
    """Resolve which coordinate family ``columns`` declares, refusing ambiguity.

    Raises ``ValueError`` — with a message naming the offending set — when no family is
    complete (the dump has no mappable coordinates) or when more than one family is
    complete (the file cannot be read honestly). The parser maps these to its own
    format-prefixed ``ParseIssue`` codes; the core stays free of the error contract so
    both v1.3 LAMMPS formats share it.
    """
    present = [
        kind for kind, family in _FAMILIES.items() if all(name in columns for name in family)
    ]
    if len(present) == 1:
        family = _FAMILIES[present[0]]
        return CoordinateColumns(kind=present[0], columns=family)
    if not present:
        raise ValueError(
            "no complete coordinate column family in header; expected one of x/y/z, "
            "xs/ys/zs, or xu/yu/zu"
        )
    raise ValueError(
        "more than one coordinate column family is complete; the file is ambiguous about "
        f"which reading is authoritative: {[f.value for f in present]}"
    )


def coordinate_note(kind: CoordinateKind) -> str:
    """The ``parse_notes`` sentence recording the coordinate interpretation in force."""
    if kind is CoordinateKind.CARTESIAN:
        return "Coordinates read as wrapped Cartesian (x/y/z); converted to canonical Å."
    if kind is CoordinateKind.SCALED:
        return (
            "Coordinates read as scaled (xs/ys/zs); converted to Cartesian Å via the box lattice."
        )
    return "Coordinates read as unwrapped Cartesian (xu/yu/zu); converted to canonical Å."
