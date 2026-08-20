"""Type↔species machinery for LAMMPS (M46; the shared `_lammps` core).

A dump carries per-atom species either as an **element-labeled** column (``element``/
``symbol``, holding symbols like ``Si``/``O``) or as a numeric ``type`` column (1-based
atom types). The canonical model requires element symbols (Part 2 §3.3), so:

* an element-labeled dump needs nothing — the symbols are read directly (validated
  against the element table; an unknown value is a malformed file, refused);
* a typed dump resolves through the existing ``missing_species`` recovery scenario
  (Part 4 §3.3) exactly as Part 3 §7.2's skeletal LAMMPS example anticipates: the
  parser raises the recoverable ``LAMMPSDUMP_MISSING_SPECIES`` issue
  (``recovery_hint="supply_species"``, the same hint the VASP-4 POSCAR path uses), and
  under a ``species_map`` preset this helper maps types → symbols.

The helper here is the *mechanical* half — map + validate — with **no new scenario**
(M46 adds no species machinery; it feeds the existing one). Validation is two-sided and
strict: every observed type must be named by the map (an unnamed type cannot be
resolved), and every map entry must name an observed type (a map that describes types
the file does not contain does not match this file — a mismatched map is refused, never
silently trimmed). Symbols are validated against the canonical element table.

The caller (the dump parser) owns the ParseIssue mapping; this module imports only
``schema`` (for element validation), keeping the shared core free of the error
contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from xtalate.schema.elements import is_valid_symbol

#: The element-labeled column names LAMMPS writes (``dump … element`` / a custom
#: ``element`` or ``symbol`` column). A header containing one of these is treated as
#: element-labeled; anything else numeric falls through to the type path.
ELEMENT_COLUMN_NAMES = ("element", "symbol", "elements", "symbols")


def is_element_column(name: str) -> bool:
    """Whether ``name`` is an element-labeled species column (case-sensitive)."""
    return name in ELEMENT_COLUMN_NAMES


def resolve_species(
    *,
    type_values: np.ndarray | None,
    element_column: Sequence[str] | None,
    species_map: Mapping[int, str] | list[str] | None,
) -> list[str]:
    """Per-atom element symbols for one dump frame, from its type or element column.

    Exactly one source of symbols is honored:

    * ``element_column`` — a length-N sequence of symbols; validated in full (an
      unknown symbol is a malformed file, refused) and returned as-is.
    * ``type_values`` + ``species_map`` — the 1-based numeric types resolved through
      the map (a dict ``{type: symbol}`` — integer keys, or string keys that coerce —
      or a list whose index+1 is the type). The map is validated against the observed
      type set on **both** sides (see the module docstring) and every symbol against
      the element table.

    Raises ``ValueError`` with a specific message for every refusal: no species
    information at all, a missing/extra/malformed map, or an invalid symbol. The
    parser maps the "no species information" case to the recoverable
    ``LAMMPSDUMP_MISSING_SPECIES`` issue; the other failures are malformed-input
    errors, never recovery offers.
    """
    if element_column is not None:
        symbols = list(element_column)
        for i, symbol in enumerate(symbols):
            if not is_valid_symbol(str(symbol)):
                raise ValueError(
                    f"element column value {symbol!r} at atom {i} is not a valid element symbol"
                )
        return symbols
    if type_values is None:
        raise ValueError(
            "no species information: the dump has no element column, and no type column "
            "to resolve through a species_map"
        )
    if species_map is None:
        raise ValueError(
            "numeric atom types need a species_map preset to resolve to elements "
            "(missing_species recovery)"
        )
    resolved = _resolve_types(type_values, species_map)
    return resolved


def _resolve_types(
    type_values: np.ndarray, species_map: Mapping[int, str] | list[str]
) -> list[str]:
    """Map a numeric type column to symbols under a validated ``species_map``."""
    types = np.asarray(type_values)
    if types.ndim != 1 or types.shape[0] == 0:
        raise ValueError(f"type column must be a non-empty 1-D array, got shape {types.shape}")
    if not np.issubdtype(types.dtype, np.integer) or bool(np.any(types < 1)):
        raise ValueError("type column values must be positive integers (1-based LAMMPS types)")
    observed = sorted({int(t) for t in types})

    mapping: dict[int, str] = {}
    if isinstance(species_map, Mapping):
        for raw_key, symbol in species_map.items():
            try:
                key = int(raw_key)
            except (TypeError, ValueError):
                raise ValueError(
                    f"species_map key {raw_key!r} is not an integer atom type"
                ) from None
            if key in mapping:
                raise ValueError(f"species_map names type {key} more than once")
            mapping[key] = str(symbol)
    else:  # list — index + 1 is the type (the POSCAR species_map analogue)
        for key, symbol in enumerate(species_map, start=1):
            mapping[key] = str(symbol)

    missing = [t for t in observed if t not in mapping]
    if missing:
        raise ValueError(
            f"species_map does not name observed type(s) {missing}; the file cannot be "
            "resolved to elements"
        )
    extra = sorted(set(mapping) - set(observed))
    if extra:
        raise ValueError(
            f"species_map names type(s) {extra} that the file does not contain — the map "
            "does not match this dump (a mismatched map is refused, never trimmed)"
        )
    symbols = [mapping[t] for t in types]
    for i, symbol in enumerate(symbols):
        if not is_valid_symbol(symbol):
            raise ValueError(
                f"species_map symbol {symbol!r} for type {int(types[i])} is not a valid "
                "element symbol"
            )
    return symbols
