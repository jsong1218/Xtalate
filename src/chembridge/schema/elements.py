"""Chemical element symbol <-> atomic number table (MASTER_SPEC Part 2 §3.3).

``AtomsBlock`` carries both ``symbols`` and ``atomic_numbers``; the numbers are derived
from the symbols at construction (§3.3) and validated for agreement. This module is the
single source of that mapping. The reserved pseudo-element ``"X"`` (unknown species,
atomic number 0) is valid, but a parser emitting it must accompany it with a warning
(§3.3) — that policy lives in the parsers, not here.
"""

from __future__ import annotations

# Symbols indexed by atomic number: SYMBOLS[Z] == symbol. Index 0 is the reserved
# unknown-species marker "X" (§3.3). Covers Z = 1..118 (all IUPAC-named elements).
_SYMBOLS: tuple[str, ...] = (
    "X",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
)

#: symbol -> atomic number (Z). "X" maps to 0.
SYMBOL_TO_Z: dict[str, int] = {sym: z for z, sym in enumerate(_SYMBOLS)}

#: The reserved symbol for an unidentified species (§3.3).
UNKNOWN_SYMBOL = "X"


def is_valid_symbol(symbol: str) -> bool:
    """True if ``symbol`` is an element symbol or the reserved ``"X"`` (§3.3)."""
    return symbol in SYMBOL_TO_Z


def atomic_number(symbol: str) -> int:
    """Atomic number for ``symbol``. Raises ``KeyError`` for an unknown symbol."""
    return SYMBOL_TO_Z[symbol]
