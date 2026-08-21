"""Shared LAMMPS core (v1.3 M46–M47; Part 3 §7.2).

The conversion primitives both v1.3 LAMMPS formats reuse — per-style unit tables,
triclinic box↔lattice mapping, type↔species resolution (feeding the existing
``missing_species`` scenario), and coordinate-column semantics. Housed under ``sdk`` —
not ``parsers`` — because the M47 dump **exporter** applies the same tables in the
inverse direction, and ``parsers``/``exporters`` are sibling import-linter layers that
may not import each other (P2, Part 1 §5.1): a shared core below both is the only home
both sides can reach. It holds **no** parser: the dump parser (M46-S2), the dump
``exporter`` (M47-S1), and the data parser (M48) are separate modules that drive these
primitives.
"""

from __future__ import annotations

from xtalate.sdk.lammps.box import (
    Box,
    box_from_bounds,
    box_from_edges,
    edges_from_box,
    scaled_to_cartesian,
)
from xtalate.sdk.lammps.columns import (
    COORDINATE_COLUMN_NAMES,
    CoordinateColumns,
    CoordinateKind,
    coordinate_note,
    resolve_coordinate_columns,
)
from xtalate.sdk.lammps.species import (
    ELEMENT_COLUMN_NAMES,
    is_element_column,
    resolve_species,
)
from xtalate.sdk.lammps.units import UNIT_STYLES, UnitStyle, unit_style

__all__ = [
    "Box",
    "COORDINATE_COLUMN_NAMES",
    "CoordinateColumns",
    "CoordinateKind",
    "ELEMENT_COLUMN_NAMES",
    "UNIT_STYLES",
    "UnitStyle",
    "box_from_bounds",
    "box_from_edges",
    "coordinate_note",
    "edges_from_box",
    "is_element_column",
    "resolve_coordinate_columns",
    "resolve_species",
    "scaled_to_cartesian",
    "unit_style",
]
