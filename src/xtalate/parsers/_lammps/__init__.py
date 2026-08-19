"""Shared LAMMPS core (v1.3 M46; Part 3 §7.2).

The conversion primitives both v1.3 LAMMPS formats reuse — per-style unit tables,
triclinic box↔lattice mapping, type↔species resolution (feeding the existing
``missing_species`` scenario), and coordinate-column semantics. A subpackage under
``parsers/``, it inherits that layer's import contract (``schema`` + ``sdk`` only) and
holds **no** parser: the dump parser (M46-S2) and the data parser (M48) are separate
modules that drive these primitives.
"""

from __future__ import annotations

from xtalate.parsers._lammps.box import Box, box_from_bounds, scaled_to_cartesian
from xtalate.parsers._lammps.columns import (
    COORDINATE_COLUMN_NAMES,
    CoordinateColumns,
    CoordinateKind,
    coordinate_note,
    resolve_coordinate_columns,
)
from xtalate.parsers._lammps.species import (
    ELEMENT_COLUMN_NAMES,
    is_element_column,
    resolve_species,
)
from xtalate.parsers._lammps.units import UNIT_STYLES, UnitStyle, unit_style

__all__ = [
    "Box",
    "COORDINATE_COLUMN_NAMES",
    "CoordinateColumns",
    "CoordinateKind",
    "ELEMENT_COLUMN_NAMES",
    "UNIT_STYLES",
    "UnitStyle",
    "box_from_bounds",
    "coordinate_note",
    "is_element_column",
    "resolve_coordinate_columns",
    "resolve_species",
    "scaled_to_cartesian",
    "unit_style",
]
