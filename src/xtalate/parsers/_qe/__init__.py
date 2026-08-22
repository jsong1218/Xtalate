"""Shared Quantum ESPRESSO mapping core (v1.4 M50-S1; DECISIONS.md D189).

Pure mapping functions from *parsed pw.x values* → canonical fields, with **no namelist,
card, or tokenizing knowledge** — so both the pw.x input parser (M50) and the pw.x output
parser (M52) feed it, and two parsers reading one calculation cannot co-discover divergent
mappings (the divergence risk the shared core exists to prevent — the exact ``_vasp``/D160
precedent, for the exact reason: two artifacts of one calculation must agree; the input
parser is the honest place to pin QE's structural conventions against machine-checkable
ground truth before the log parser co-discovers them). It is a mapping layer, not a reader:
it imports only ``xtalate.schema`` (and numpy), never a tokenizing module, never another
parser (P2).

QE declares its units **in the file** — every per-card unit conversion is a deterministic
boundary mapping recorded in ``parse_notes``, **never a scenario** (the VASP contrast of
v1.2, not the LAMMPS ambiguity of v1.3). There is deliberately **no ``ambiguous_units`` /
``ambiguous_*`` machinery anywhere in this core**: a pw.x input that states ``{bohr}`` is
converted with the exact factor below, and one that states ``{alat}`` without a resolvable
``celldm(1)``/``A`` is refused by the reader — never asked, never guessed.

The core owns the mapping *decisions* so they are pinned in exactly one place:

* **Bohr → Å** — the exact CODATA Bohr radius QE itself uses (``Modules/constants.f90``,
  ``bohr_radius_angs``), pinned by a hand-computed fixture, never eyeballed.
* **alat-relative → Å** — resolved against the declared ``celldm(1)`` (Bohr) or ``A`` (Å);
  when both are present, ``A`` wins (QE's documented precedence), and the note records
  which spelling was used.
* **crystal (fractional) → Cartesian** — the plain ``frac @ lattice`` product against the
  cell in force (the explicit ``CELL_PARAMETERS`` in M50-S1; the *derived* lattice from
  M50-S2's ``ibrav`` expansion once it lands).
* **Provenance** — per-card ``source_units`` as read, ``original_coordinate_system``
  (``"cartesian"`` for angstrom/bohr/alat; ``"fractional"`` for crystal — the POSCAR
  precedent), and the ``parse_notes`` entries recording every conversion. ``ibrav``
  expansion is deliberately **absent** here in M50-S1 — it lands in M50-S2 as a core
  addition, so S1's core is expansion-free and complete on its own.

Every conversion helper returns the converted values **plus the note string** the reader
records — a conversion in this core is never silent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

import numpy as np

from xtalate.schema.cell import to_cartesian

#: The exact Bohr radius (in Å) QE uses in ``Modules/constants.f90``
#: (``bohr_radius_angs = 0.52917720859_dp``). Pinned by hand-computed fixtures in the
#: M50 goldens — a wrong factor would be a silent scale error at MLIP scale, the same
#: failure class D161 names for VASP's kBar factor.
BOHR_TO_ANGSTROM = 0.52917720859

#: The per-card units a pw.x input can declare (QE's documented vocabulary).
POSITION_UNITS = ("angstrom", "bohr", "alat", "crystal")
CELL_UNITS = ("angstrom", "bohr", "alat")

#: The coordinate *system* a unit denotes — what ``original_coordinate_system`` records
#: (the POSCAR precedent): angstrom/bohr/alat are Cartesian frames at different scales,
#: crystal is fractional.
_CARTESIAN_UNITS = frozenset({"angstrom", "bohr", "alat"})

_RowSeq: TypeAlias = Sequence[Sequence[float]] | np.ndarray

_PBC_NOTE = (
    "pbc set to (true,true,true): a pw.x input carries no PBC declaration and QE is always "
    "fully periodic (format-defined, not assumed)."
)


def pbc_note() -> str:
    """The provenance ``parse_notes`` entry for QE's format-defined full periodicity."""
    return _PBC_NOTE


def coordinate_system(unit: str) -> str:
    """The canonical ``original_coordinate_system`` string for a declared per-card unit:
    ``"cartesian"`` for angstrom/bohr/alat, ``"fractional"`` for crystal (the POSCAR
    vocabulary — nothing about the source coordinate system is lost, because the unit
    itself is recorded in ``source_units`` and the conversion in ``parse_notes``)."""
    if unit == "crystal":
        return "fractional"
    if unit in _CARTESIAN_UNITS:
        return "cartesian"
    raise ValueError(f"unknown QE unit {unit!r}")


def alat_angstrom(
    *, celldm1: float | None = None, a: float | None = None
) -> tuple[float | None, str | None]:
    """QE's lattice parameter ``alat`` in Å, resolved from the declared spellings.

    ``celldm(1)`` states alat in **Bohr**; ``A`` states it in **Å**. When both are present,
    ``A`` wins (QE's documented precedence — ``celldm(1)`` is ignored). Returns
    ``(None, None)`` when neither is declared, and the caller (the reader) refuses any
    alat-relative conversion rather than fabricate QE's 1-Bohr default (**P3**). The note
    names the spelling used, so the resolution is never silent.
    """
    if a is not None:
        return float(a), (
            "alat resolved from &system A (angstrom); QE prefers A over celldm(1) when both "
            "are declared."
        )
    if celldm1 is not None:
        alat = float(celldm1) * BOHR_TO_ANGSTROM
        return alat, (
            f"alat resolved from &system celldm(1) ({celldm1!r} bohr) × {BOHR_TO_ANGSTROM} "
            "(QE's CODATA bohr radius) → {alat!r} Å."
        ).format(alat=alat)
    return None, None


def lattice_from_cell_parameters(
    rows: _RowSeq, unit: str, *, alat: float | None = None
) -> tuple[np.ndarray, str]:
    """Canonical ``cell.lattice_vectors`` (Å, rows a/b/c) from a ``CELL_PARAMETERS`` block.

    ``unit`` is the card's declared unit (``"angstrom"``/``"bohr"``/``"alat"`` — the bare
    card reads as ``alat`` per QE's documented default, which the reader records). Returns
    the 3×3 matrix plus the note string the reader records. Raises ``ValueError`` when the
    conversion needs an alat it was not given (the reader turns that into the parse-error
    contract — never a guessed scale).
    """
    what = "CELL_PARAMETERS"
    if unit == "angstrom":
        return np.asarray(rows, dtype=float), (
            f"{what} {{angstrom}}: lattice vectors read as-is (Å)."
        )
    if unit == "bohr":
        out = np.asarray(rows, dtype=float) * BOHR_TO_ANGSTROM
        return out, (
            f"{what} {{bohr}}: lattice vectors converted Bohr → Å "
            f"(× {BOHR_TO_ANGSTROM}, QE's CODATA bohr radius)."
        )
    if unit == "alat":
        if alat is None:
            raise ValueError(
                "CELL_PARAMETERS {alat} declared but no alat is resolvable from &system "
                "(celldm(1)/A absent); refusing rather than assuming a scale"
            )
        out = np.asarray(rows, dtype=float) * alat
        return out, f"{what} {{alat}}: lattice vectors scaled to Å via alat ({alat!r} Å)."
    raise ValueError(f"{what} declares unsupported unit {unit!r} (angstrom|bohr|alat)")


def positions_cartesian(
    rows: _RowSeq, unit: str, *, lattice: np.ndarray, alat: float | None = None
) -> tuple[np.ndarray, str]:
    """Canonical Cartesian positions (Å) from an ``ATOMIC_POSITIONS`` block.

    ``unit`` is the card's declared unit (``"angstrom"``/``"bohr"``/``"alat"``/``"crystal"``;
    the bare card reads as ``alat`` per QE's documented default, which the reader records).
    ``angstrom`` reads as-is; ``bohr`` and ``alat`` scale by the exact factor; ``crystal``
    converts fractional → Cartesian against ``lattice`` (rows a/b/c). Returns the (N, 3)
    array plus the note string the reader records. Raises ``ValueError`` when the
    conversion needs an alat it was not given.
    """
    what = "ATOMIC_POSITIONS"
    if unit == "angstrom":
        return np.asarray(rows, dtype=float), (
            f"{what} {{angstrom}}: Cartesian positions read as-is (Å)."
        )
    if unit == "bohr":
        out = np.asarray(rows, dtype=float) * BOHR_TO_ANGSTROM
        return out, (
            f"{what} {{bohr}}: positions converted Bohr → Å "
            f"(× {BOHR_TO_ANGSTROM}, QE's CODATA bohr radius)."
        )
    if unit == "alat":
        if alat is None:
            raise ValueError(
                "ATOMIC_POSITIONS {alat} declared but no alat is resolvable from &system "
                "(celldm(1)/A absent); refusing rather than assuming a scale"
            )
        out = np.asarray(rows, dtype=float) * alat
        return out, f"{what} {{alat}}: positions scaled to Å via alat ({alat!r} Å)."
    if unit == "crystal":
        out = to_cartesian(np.asarray(rows, dtype=float), lattice)
        return out, (
            f"{what} {{crystal}}: fractional (crystal) coordinates converted to Cartesian Å "
            "via the lattice matrix."
        )
    raise ValueError(f"{what} declares unsupported unit {unit!r} (angstrom|bohr|alat|crystal)")
