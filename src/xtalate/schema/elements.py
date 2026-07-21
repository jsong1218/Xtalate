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


def normalize_symbol(raw: str) -> str | None:
    """``raw`` as a canonical element symbol (``FE``/``fe``/``Fe`` → ``Fe``), or ``None``.

    Case is not information: ``FE`` and ``Fe`` are the same element, and which one a file writes is
    a fact about the file's typography, not about the structure. So normalizing is not laundering —
    unlike, say, rewriting a coordinate, nothing a source stated is changed by it.

    It lives here rather than in a parser because "what counts as a spelling of iron" is a fact
    about the element table, and the CIF parser had the only copy — which meant ``FE`` parsed as
    iron from a CIF and was rejected from an XYZ, the same content reading differently by format.

    **Note the deliberate limit:** this is the shared *definition*; the other Phase 1 parsers still
    call :func:`is_valid_symbol` on the raw string and so still reject ``FE``. Widening what XYZ,
    POSCAR or XDATCAR accept changes those formats' contracts and wants its own decision and
    fixtures — it is not a side effect to smuggle in under a refactor.
    """
    stripped = raw.strip()
    if not stripped:
        return None
    candidate = stripped[0].upper() + stripped[1:].lower()
    return candidate if candidate in SYMBOL_TO_Z else None


def atomic_number(symbol: str) -> int:
    """Atomic number for ``symbol``. Raises ``KeyError`` for an unknown symbol."""
    return SYMBOL_TO_Z[symbol]
