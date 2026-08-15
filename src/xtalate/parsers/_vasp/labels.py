"""The shared VASP label-extraction mappings (v1.2 M42-S2; DECISIONS.md D160).

Pure functions from *parsed VASP values* → canonical fields. A reader (vasprun.xml now,
OUTCAR in M43) does the file-specific work — XML elements or log lines — and hands this
module the resulting numbers; it never parses text or XML itself. Every mapping decision
lives here so the two readers reuse it verbatim.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

import numpy as np

from xtalate.schema import Cell
from xtalate.schema.elements import SYMBOL_TO_Z, is_valid_symbol

#: A reader may hand the core lists or ndarrays; both are "parsed VASP values".
_RowSeq: TypeAlias = Sequence[Sequence[float]] | np.ndarray

#: The VASP ``<energy>`` block tag mapped to canonical ``electronic.total_energy``, and why
#: (D160). VASP extrapolates the total energy to zero smearing width and reports it both as
#: ``e_0_energy`` in vasprun.xml and as ``energy(sigma->0)`` in OUTCAR; the canonical field is
#: the electronic ground-state total energy, so that extrapolated value is the mapping (it is
#: also the value pymatgen's ``Vasprun.final_energy`` selects). The free energy
#: (``e_fr_energy``, VASP's TOTEN) includes the finite-smearing entropy term — a
#: temperature-dependent free energy, not the total energy — so it is never substituted; a
#: reader carries it (and the other energy-block scalars) verbatim instead.
TOTAL_ENERGY_TAG = "e_0_energy"

#: The exact kBar → eV/Å³ factor: 1 eV/Å³ = 1602.1766208 kBar (1 eV = 1.6021766208e-19 J,
#: 1 Å = 1e-10 m, 1 kBar = 1e8 Pa). Pinned by a hand-computed fixture — a wrong factor would
#: be a silent scale error at MLIP scale (D161).
K_BAR_PER_EV_A3 = 1602.1766208

_PBC_NOTE = (
    "pbc set to (true,true,true): vasprun.xml carries no PBC declaration and VASP is always "
    "fully periodic (format-defined, not assumed)."
)
_DIRECT_NOTE = (
    "Direct (fractional) coordinates converted to Cartesian using each step's lattice matrix."
)
_CARTESIAN_NOTE = "Cartesian coordinates read as-is (angstrom)."
_ENERGY_NOTE = (
    f"electronic.total_energy read from the <energy> block's {TOTAL_ENERGY_TAG} (VASP's energy "
    "extrapolated to zero smearing, the energy(sigma->0) value); other energy-block scalars are "
    "carried verbatim in user_metadata.custom_per_frame['vasprun:*']."
)
_SOURCE_CODE_NOTE = (
    "simulation.source_code set to the program string declared in <generator> (verbatim)."
)
_CELL_NOTE = "cell.lattice_vectors assembled from the <crystal> basis varray (rows a, b, c)."
_STEP_CELL_NOTE = (
    "Each <calculation>'s own <structure> supplies that step's cell and positions; a step "
    "without one reuses the previous step's (the fixed-cell form)."
)
_STRESS_NOTE = (
    "electronic.stress mapped from VASP's kBar tensor when a <calculation> carries a "
    '<varray name="stress">: VASP reports pressure (compression-positive) in kBar, so the '
    "tensor is sign-flipped to canonical tension-positive and divided by the exact factor "
    f"{K_BAR_PER_EV_A3} kBar per eV/Å³ (D161). A step without a stress block leaves "
    "electronic.stress None (P3 — absence is never defaulted)."
)

#: The canonical notes for a fully-populated vasprun.xml parse, in a stable order — assembled
#: here (not in the reader) so the mapping layer owns the prose a conversion will record.
_NOTES_DIRECT = [
    _DIRECT_NOTE,
    _PBC_NOTE,
    _ENERGY_NOTE,
    _SOURCE_CODE_NOTE,
    _CELL_NOTE,
    _STEP_CELL_NOTE,
    _STRESS_NOTE,
]
_NOTES_CARTESIAN = [
    _CARTESIAN_NOTE,
    _PBC_NOTE,
    _ENERGY_NOTE,
    _SOURCE_CODE_NOTE,
    _CELL_NOTE,
    _STEP_CELL_NOTE,
    _STRESS_NOTE,
]


def parse_notes_for(mode: str) -> list[str]:
    """The provenance ``parse_notes`` for a fully-mapped vasprun.xml read under ``mode``."""
    return list(_NOTES_CARTESIAN if mode == "cartesian" else _NOTES_DIRECT)


def coordinate_parse_note(mode: str) -> str:
    """The single coordinate-mapping note for ``mode`` (``"direct"`` or ``"cartesian"``)."""
    return _CARTESIAN_NOTE if mode == "cartesian" else _DIRECT_NOTE


def energy_parse_note() -> str:
    return _ENERGY_NOTE


def source_code_parse_note() -> str:
    return _SOURCE_CODE_NOTE


def stress_parse_note() -> str:
    return _STRESS_NOTE


def pbc_parse_note() -> str:
    return _PBC_NOTE


def cell_parse_note() -> str:
    return _CELL_NOTE


def symbols_from_species(species: Sequence[tuple[int, int]]) -> list[str]:
    """The per-atom symbol list from the VASP species table.

    ``species`` is ``[(z, count), ...]`` in declared species order (the ``atomtypes`` array's
    atomic-number column, one entry per species). Returns one symbol per atom, in species
    order — the canonical constant-``N`` ``atoms.symbols`` list. Raises ``KeyError`` for an
    atomic number with no element symbol (the reader turns it into the parse-error contract).
    """
    symbols: list[str] = []
    for z, count in species:
        symbol = _symbol_for_z(int(z))
        symbols.extend([symbol] * int(count))
    return symbols


def _symbol_for_z(z: int) -> str:
    for symbol, zz in SYMBOL_TO_Z.items():
        if zz == z:
            return symbol
    raise KeyError(f"no element symbol for atomic number {z!r}")


def symbols_from_symbol_counts(species: Sequence[tuple[str, int]]) -> list[str]:
    """The per-atom symbol list from declared ``(symbol, count)`` species — OUTCAR's form (M43).

    OUTCAR states its species as element **symbols** (from the POTCAR ``VRHFIN =X:`` lines) with
    per-species counts (``ions per type``), not as atomic numbers the way vasprun.xml's
    ``atomtypes`` Z column does (D160). The symbols are validated against the element table (the
    single source, ``SYMBOL_TO_Z``) and expanded in declared species order — one symbol per atom,
    the canonical constant-``N`` ``atoms.symbols`` list. An unknown symbol raises ``KeyError`` for
    the reader to turn into the parse-error contract (never a guessed placeholder — the same
    missing-species discipline as XDATCAR's species line).
    """
    symbols: list[str] = []
    for symbol, count in species:
        if not is_valid_symbol(symbol):
            raise KeyError(f"unknown element symbol {symbol!r}")
        symbols.extend([symbol] * int(count))
    return symbols


def lattice_vectors(rows: _RowSeq) -> np.ndarray:
    """The 3×3 lattice matrix from the ``<crystal>`` basis rows (rows a, b, c, Å)."""
    return np.asarray(rows, dtype=float)


def build_cell(rows: _RowSeq) -> Cell:
    """A canonical :class:`Cell` from the basis rows — ``pbc`` (T,T,T) by format definition."""
    return Cell(lattice_vectors=lattice_vectors(rows), pbc=(True, True, True))


def positions_from_fractional(frac: _RowSeq, lattice: np.ndarray) -> np.ndarray:
    """Cartesian Å from direct (fractional) rows times the step's lattice (rows a, b, c)."""
    out: np.ndarray = np.asarray(frac, dtype=float) @ lattice
    return out


def positions_cartesian(xyz: _RowSeq) -> np.ndarray:
    """Cartesian positions, read as-is (Å)."""
    return np.asarray(xyz, dtype=float)


def positions(raw: _RowSeq, lattice: np.ndarray, *, mode: str) -> np.ndarray:
    """Canonical Cartesian positions (Å) for one step's coordinate rows.

    ``mode`` is the reader's read of the positions varray's ``mode`` attribute (or the
    format default): ``"cartesian"`` reads the rows as-is; anything else (including the
    absent-attribute default) treats the rows as direct (fractional) coordinates converted
    through ``lattice``.
    """
    if mode == "cartesian":
        return positions_cartesian(raw)
    return positions_from_fractional(raw, lattice)


def total_energy(e_0: float) -> float:
    """Canonical ``electronic.total_energy`` in eV: VASP's ``e_0_energy`` (extrapolated to
    zero smearing). The value is stored verbatim — VASP already writes canonical eV."""
    return float(e_0)


def stress_from_vasp_kbar(stress_kbar: _RowSeq) -> np.ndarray:
    """Canonical tension-positive ``electronic.stress`` (eV/Å³, full symmetric 3×3).

    VASP writes its stress tensor in **kBar, compression-positive** (pressure); canonical is
    **tension-positive** eV/Å³ (Part 2 §3.7.1). The mapping is deterministic — VASP declares
    its convention, so it is computed and recorded, never asked (no
    ``ambiguous_stress_convention`` for a VASP source, D161).
    """
    out: np.ndarray = -np.asarray(stress_kbar, dtype=float) / K_BAR_PER_EV_A3
    return out


def stress_voigt6_vasp_to_full(voigt6: Sequence[float]) -> np.ndarray:
    """The symmetric 3×3 tensor from VASP's 6-component Voigt line, **VASP ordering**
    ``[XX, YY, ZZ, XY, YZ, ZX]`` (the OUTCAR ``in kB`` stress line; M43's reader reuses this).

    Deliberately **not** ASE's ``voigt_6_to_full_3x3_stress`` ordering
    (``[xx, yy, zz, yz, xz, xy]``): coupling the two orderings would silently **transpose the
    off-diagonal stress components** — the exact silent-bug hazard D161 names. This helper is
    ordering-only; the caller applies the kBar→eV/Å³ unit + compression→tension sign flip via
    :func:`stress_from_vasp_kbar`.
    """
    xx, yy, zz, xy, yz, zx = voigt6
    return np.asarray(
        [
            [xx, xy, zx],
            [xy, yy, yz],
            [zx, yz, zz],
        ],
        dtype=float,
    )


def forces(raw: _RowSeq) -> np.ndarray:
    """Canonical ``dynamics.forces`` in eV/Å, verbatim (VASP already writes canonical units)."""
    return np.asarray(raw, dtype=float)
