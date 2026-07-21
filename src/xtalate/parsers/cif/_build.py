"""Stage 4 of the CIF reader: validated document → Canonical Object (DECISIONS.md D65).

The only stage that knows ``xtalate.schema`` exists. Everything requiring canonical knowledge
lives here: the element table, unit conventions, the fractional→Cartesian conversion, and the
absence convention (**P3**).

Two format-defined facts are recorded in ``parse_notes`` rather than guessed (Part 3 §5 rule 3):
full 3-D periodicity, which CIF implies by describing a crystal and never states as a tag
(§3 n.3), and the coordinate conversion itself. Nothing else is added to the structure.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from xtalate.parsers._common import build_provenance
from xtalate.parsers.cif._document import CifBlock, CifLoop
from xtalate.parsers.cif._validate import (
    CELL_ANGLE_TAGS,
    CELL_LENGTH_TAGS,
    FRACT_TAGS,
    LABEL_TAG,
    SPACE_GROUP_NAME_TAGS,
    TYPE_SYMBOL_TAG,
    has_uncertainty,
    parse_number,
    validate_atom_sites,
    validate_cell,
    validate_expandable,
)
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    SimulationMetadata,
    UserMetadata,
)
from xtalate.schema.elements import is_valid_symbol
from xtalate.sdk import ParseError, ParseIssue

_PBC_NOTE = (
    "pbc set to (true,true,true): a CIF describes a crystal, so full 3-D periodicity is "
    "format-defined (Part 3 §3 n.3), not assumed."
)
_FRACTIONAL_NOTE = (
    "Fractional coordinates converted to Cartesian using the lattice matrix built from "
    "_cell_length_* / _cell_angle_* (Part 2 §4)."
)
_CARTESIAN_NOTE = "Cartesian _atom_site_Cartn_* coordinates read verbatim in Å (Part 2 §4)."
_UNCERTAINTY_NOTE_PREFIX = (
    "source values carried a parenthesized standard uncertainty, which was read as the value "
    "and whose precision digits are not modelled: "
)

# Structural _atom_site columns the builder maps to canonical fields. Every *other* column in
# the loop is carried verbatim into custom_per_atom, so a tag this version does not understand
# (occupancy, Wyckoff symbols, displacement parameters) is preserved rather than dropped (P1).
_CONSUMED_SITE_TAGS = frozenset(
    {
        TYPE_SYMBOL_TAG,
        "_atom_site_fract_x",
        "_atom_site_fract_y",
        "_atom_site_fract_z",
        "_atom_site_cartn_x",
        "_atom_site_cartn_y",
        "_atom_site_cartn_z",
    }
)

# An element symbol with an optional oxidation-state suffix: "Fe", "Fe3+", "O2-", "Ca+".
_TYPE_SYMBOL = re.compile(r"^([A-Za-z]{1,2})(\d*[+-]|[+-]\d*)?$")
# A site label: element letters followed by an arbitrary site index — "O1", "Fe2A", "Ca1_2".
_LABEL = re.compile(r"^([A-Za-z]{1,2})[0-9_].*$|^([A-Za-z]{1,2})$")


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


_SQRT3_OVER_2 = math.sqrt(3.0) / 2.0
# The cell angles crystallography states *exactly*: the right angle of every non-triclinic
# system, and the 30/60/120/150° angles of the hexagonal and rhombohedral ones. libm evaluates
# cos(radians(90)) as 6.1e-17 rather than 0, so a lattice built through it is both spuriously
# non-orthogonal — a 1e-16 tilt the source never declared, which P1 has no business inventing —
# and machine-dependent in its last bit, since the platform's libm, not IEEE 754, decides that
# digit. Both problems disappear by using the exact value the angle actually denotes.
_EXACT_COS_SIN_DEG: dict[float, tuple[float, float]] = {
    30.0: (_SQRT3_OVER_2, 0.5),
    60.0: (0.5, _SQRT3_OVER_2),
    90.0: (0.0, 1.0),
    120.0: (-0.5, _SQRT3_OVER_2),
    150.0: (-_SQRT3_OVER_2, 0.5),
}


def _cos_sin_deg(degrees: float) -> tuple[float, float]:
    """``(cos, sin)`` of an angle in degrees, exact for the standard crystallographic angles."""
    exact = _EXACT_COS_SIN_DEG.get(degrees)
    if exact is not None:
        return exact
    radians = math.radians(degrees)
    return math.cos(radians), math.sin(radians)


def lattice_from_parameters(
    lengths: tuple[float, float, float], angles: tuple[float, float, float]
) -> np.ndarray:
    """Build the 3×3 lattice matrix (rows a, b, c, in Å) from cell parameters.

    CIF is the only Phase 1 format that states a cell as *parameters* rather than vectors, so
    an orientation convention has to be chosen; a≈+x with b in the xy half-plane is the
    crystallographic standard and is documented here because it is otherwise invisible. The
    choice is not observable in any physical quantity — lengths, angles, volume and all
    interatomic distances are rotation-invariant — but it *is* observable in the exported
    Cartesian coordinates, which is why it is pinned rather than left to floating-point luck.
    """
    a, b, c = lengths
    cos_alpha, _ = _cos_sin_deg(angles[0])
    cos_beta, _ = _cos_sin_deg(angles[1])
    cos_gamma, sin_gamma = _cos_sin_deg(angles[2])

    cx = c * cos_beta
    cy = c * (cos_alpha - cos_beta * cos_gamma) / sin_gamma
    cz_squared = c * c - cx * cx - cy * cy
    if cz_squared <= 0.0:
        raise _error(
            "CIF_INVALID_CELL",
            f"cell angles alpha={angles[0]}, beta={angles[1]}, gamma={angles[2]} do not "
            "describe a realizable cell (the implied volume is zero or negative)",
        )
    return np.asarray(
        [
            [a, 0.0, 0.0],
            [b * cos_gamma, b * sin_gamma, 0.0],
            [cx, cy, math.sqrt(cz_squared)],
        ],
        dtype=float,
    )


def element_of(raw_type: str | None, raw_label: str | None, *, line: int) -> str:
    """The element symbol for one site, laundered from its type symbol or label.

    ``_atom_site_type_symbol`` is preferred and carries an optional oxidation-state suffix
    (``Fe3+``); the charge part is split off here and the *raw* symbol is carried verbatim into
    ``custom_per_atom`` so M19 can reconcile it against ``_atom_type_oxidation_number`` without
    re-reading the file. Falling back to ``_atom_site_label`` (``O1``, ``Fe2A``) is a genuine
    reading of the format, not a guess — the label's leading letters are its element by CIF
    convention — but an unrecognizable one is an error, never a placeholder element.
    """
    for raw, pattern in ((raw_type, _TYPE_SYMBOL), (raw_label, _LABEL)):
        if raw is None:
            continue
        match = pattern.match(raw.strip())
        if match is None:
            continue
        symbol = next(g for g in match.groups() if g)
        symbol = symbol[0].upper() + symbol[1:].lower()
        if is_valid_symbol(symbol):
            return symbol
    raise _error(
        "CIF_INVALID_SYMBOL",
        f"cannot identify an element from type symbol {raw_type!r} / label {raw_label!r}; "
        "symbols are required and are never invented (Part 2 §3.3)",
        location=f"line {line}",
    )


def build(
    block: CifBlock, *, format_id: str, filename: str | None, parser_version: str
) -> tuple[CanonicalObject, list[ParseIssue]]:
    """Assemble the Canonical Object for one validated ``data_`` block."""
    issues: list[ParseIssue] = []
    lengths, angles = validate_cell(block)
    space_group = validate_expandable(block)
    loop, coord_tags, fractional = validate_atom_sites(block)

    lattice = lattice_from_parameters(lengths, angles)
    coords, uncertain = _coordinates(loop, coord_tags)
    positions = coords @ lattice if fractional else coords

    types = loop.column(TYPE_SYMBOL_TAG)
    labels = loop.column(LABEL_TAG)
    symbols = [
        element_of(
            types[i] if types is not None else None,
            labels[i] if labels is not None else None,
            line=loop.line,
        )
        for i in range(len(loop.rows))
    ]

    custom_per_atom = _carried_columns(loop)
    if types is not None:
        # Preserved even though it was consumed: the oxidation-state suffix is real source
        # information the element symbol alone does not carry (M19 deliverable 2).
        custom_per_atom["cif:type_symbol"] = list(types)

    parse_notes = [_FRACTIONAL_NOTE if fractional else _CARTESIAN_NOTE, _PBC_NOTE]
    if uncertain:
        parse_notes.append(f"{_UNCERTAINTY_NOTE_PREFIX}{sorted(uncertain)}")
    source_units = {
        "positions": "fractional" if fractional else "angstrom",
        "lattice_vectors": "angstrom",
    }

    extra, carried = _carried_pairs(block)
    if carried:
        issues.append(
            ParseIssue(
                severity="warning",
                code="CIF_TAGS_CARRIED",
                message=(
                    f"{len(carried)} CIF tag(s) have no canonical field and were carried "
                    f"verbatim into simulation.extra under 'cif:' keys: {sorted(carried)}"
                ),
                location=f"line {block.line}",
            )
        )

    frame = Frame(
        index=0,
        atoms=AtomsBlock(symbols=symbols, positions=positions),
        cell=Cell(lattice_vectors=lattice, pbc=(True, True, True), space_group=space_group),
    )
    canonical = CanonicalObject(
        frames=[frame],
        trajectory=None,  # a CIF block is one structure, not a time series (§3.2)
        simulation=SimulationMetadata(extra=extra) if extra else None,
        provenance=build_provenance(
            format_id=format_id,
            filename=filename,
            original_coordinate_system="fractional" if fractional else "cartesian",
            source_units=source_units,
            parse_notes=parse_notes,
            parser_version=parser_version,
        ),
        user_metadata=UserMetadata(
            custom_global={"cif:data_block_name": block.name},
            custom_per_atom=custom_per_atom,
        ),
    )
    return canonical, issues


def _coordinates(loop: CifLoop, coord_tags: tuple[str, str, str]) -> tuple[np.ndarray, set[str]]:
    """The N×3 coordinate array, plus the set of tags that carried a standard uncertainty."""
    columns = []
    uncertain: set[str] = set()
    for tag in coord_tags:
        column = loop.column(tag)
        assert column is not None  # guaranteed by validate_atom_sites
        values = []
        for row, raw in enumerate(column):
            if raw is None:
                raise _error(
                    "CIF_MISSING_COORDINATE",
                    f"{tag} is unknown ('?' or '.') for atom site {row + 1}; a position "
                    "cannot be left absent for an atom that exists (Part 2 §3.3)",
                    location=f"line {loop.line}",
                )
            if has_uncertainty(raw):
                uncertain.add(tag)
            values.append(parse_number(raw, tag=tag, line=loop.line))
        columns.append(values)
    return np.asarray(columns, dtype=float).T, uncertain


def _carried_columns(loop: CifLoop) -> dict[str, Any]:
    """Every ``_atom_site`` column with no canonical home, verbatim under a ``cif:`` key.

    This is what keeps a tag this version does not model — occupancy above all (Part 3 §3 n.11),
    but also Wyckoff symbols, displacement parameters, and the site label (``Zn1``, whose index
    the element symbol alone does not carry) — from being silently lost while M19 is unwritten.

    Values are handed over as the source spelled them; the schema's ``custom_per_atom`` union
    then stores a wholly-numeric column as a float array and anything else as strings. That
    coercion is value-preserving (``"1.000"`` → ``1.0``) and applies no CIF-specific meaning,
    which is the line that matters: this layer never *interprets* a tag it does not model.
    """
    # `Any` rather than the schema's per-atom union: that alias is private, and the union is
    # resolved by pydantic at construction (numeric column -> array, otherwise strings).
    carried: dict[str, Any] = {}
    for index, tag in enumerate(loop.tags):
        if tag in _CONSUMED_SITE_TAGS:
            continue
        carried[f"cif:{tag.lstrip('_')}"] = [row[index] for row in loop.rows]
    return carried


def _carried_pairs(block: CifBlock) -> tuple[dict[str, str], list[str]]:
    """Block-level tag→value pairs with no canonical field, verbatim under ``cif:`` keys.

    Bibliographic and free-text tags (authors, journal, chemical name, publication year) have no
    home in a schema describing atoms and cells, and dropping them would be exactly the silent
    loss this project exists to prevent (Part 3 §3 n.9).
    """
    # The space-group *name* tags are excluded because they are mapped to cell.space_group;
    # carrying them here as well would duplicate one source fact in two canonical places, and a
    # later exporter reading both would have to decide which one wins.
    consumed = {
        *(t.lower() for t in CELL_LENGTH_TAGS),
        *(t.lower() for t in CELL_ANGLE_TAGS),
        *(t.lower() for t in SPACE_GROUP_NAME_TAGS),
    }
    extra: dict[str, str] = {}
    carried: list[str] = []
    for tag, value in block.pairs.items():
        if tag in consumed or value is None:
            continue
        extra[f"cif:{tag.lstrip('_')}"] = value
        carried.append(tag)
    return extra, carried


__all__ = ["FRACT_TAGS", "build", "element_of", "lattice_from_parameters"]
