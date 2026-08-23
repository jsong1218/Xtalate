"""Shared Quantum ESPRESSO mapping core (v1.4 M50-S1/S2; DECISIONS.md D189/D190).

Pure mapping functions from *parsed pw.x values* → canonical fields, with **no namelist,
card, or tokenizing knowledge** — so both the pw.x input parser (M50) and the pw.x output
parser (M52) feed it, and two parsers reading one calculation cannot co-discover divergent
mappings (the divergence risk the shared core exists to prevent — the exact ``_vasp``/D160
precedent, for the exact reason: two artifacts of one calculation must agree; the input
parser is the honest place to pin QE's structural conventions against machine-checkable
ground truth before the log parser co-discovers them). It is a mapping layer, not a reader:
it imports only ``xtalate.schema`` (and numpy/math), never a tokenizing module, never
another parser (P2).

QE declares its units **in the file** — every per-card unit conversion is a deterministic
boundary mapping recorded in ``parse_notes``, **never a scenario** (the VASP contrast of
v1.2, not the LAMMPS ambiguity of v1.3). There is deliberately **no ``ambiguous_units`` /
``ambiguous_*`` machinery anywhere in this core**: a pw.x input that states ``{bohr}`` is
converted with the exact factor below, and one that states ``{alat}`` without a resolvable
``celldm(1)``/``A`` is refused by the reader — never asked, never guessed.

The core owns the mapping *decisions* so they are pinned in exactly one place:

* **Bohr → Å** — the exact CODATA Bohr radius QE itself uses (``Modules/constants.f90``,
  ``bohr_radius_angs``), pinned by a hand-computed fixture, never eyeballed.
* **alat-relative → Å** — resolved against the declared ``celldm(1)`` (Bohr) or ``A`` (Å).
  QE's documented contract for the two spellings is **"specify either, NOT both"**
  (INPUT_PW ``&system``/``ibrav``); both-present is a QE-invalid combination and is refused
  (D190) — the reader passes exactly one source. This corrects S1's note, which claimed
  "A wins over celldm(1) when both are declared": that silent preference is a guessed
  resolution between two disagreeing sources (the D190 rejected alternative, P4).
* **crystal (fractional) → Cartesian** — the plain ``frac @ lattice`` product against the
  cell in force: the explicit ``CELL_PARAMETERS`` for ``ibrav = 0`` (M50-S1), or the
  *derived* lattice from ``ibrav ≠ 0`` (M50-S2) — the cross case a golden pins.
* **``ibrav`` expansion (M50-S2)** — ``lattice_from_ibrav`` turns (``ibrav`` + one
  parameter spelling) into the explicit 3×3 lattice, following QE's documented lattice
  conventions **exactly** (``Modules/latgen.f90`` ``latgen_lib``; INPUT_PW v7.5 ``ibrav``
  table): supported set ``1, 2, 3, 4, 6, 8, 12, -12, 14`` (plus ``0`` = explicit, the
  reader's path), each value's vectors hand-pinned by fixture; an unsupported value
  refuses ``UnsupportedIbravError`` (the reader's ``QEIN_UNSUPPORTED_IBRAV``) — **never a
  guessed or partial lattice** (P4), and the set grows by corpus evidence (M53), not
  speculatively. Both parameter spellings — ``celldm(1..6)`` (alat in Bohr, ratios +
  cosines) and ``A,B,C,cosAB,cosAC,cosBC`` (Å + cosines, mapped per ``abc2celldm``) — reach
  identical vectors for the same lattice.
* **Species labels → elements (M50-S3)** — ``species_symbol`` applies QE's documented
  label rule (the element is the leading 1–2 characters of the ``ATOMIC_SPECIES`` label
  that form an element symbol, case-insensitively — try the 2-character prefix first,
  then the 1-character; ``Fe1`` → Fe, ``O_vac`` → O), composed with
  ``schema.elements.normalize_symbol`` — the shared element table stays the single
  authority, and QE's *decoration* rule lives here (M52's output parser reuses it). The
  reserved pseudo-element ``X`` (the schema's unknown-species marker) is a symbol in that
  table, so a label whose leading character is X resolves to the marker (``Xx`` → ``X``,
  recorded — never silently a real element); a label whose leading 1–2 characters form
  *no* symbol at all resolves to ``None`` — the reader turns that into
  ``QEIN_UNRESOLVED_SPECIES_LABEL``, recoverable through the existing ``missing_species``
  scenario (D191).
* **Provenance** — per-card ``source_units`` as read, ``original_coordinate_system``
  (``"cartesian"`` for angstrom/bohr/alat; ``"fractional"`` for crystal — the POSCAR
  precedent), and the ``parse_notes`` entries recording every conversion and every
  derivation.

Every conversion helper returns the converted values **plus the note string** the reader
records — a conversion in this core is never silent.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TypeAlias

import numpy as np

from xtalate.schema.cell import to_cartesian
from xtalate.schema.elements import normalize_symbol

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

#: The (a, b, c, cosAB, cosAC, cosBC) crystallographic spelling, each length/cosine absent
#: (``None``) when not declared.
_AbcParams: TypeAlias = tuple[
    float | None, float | None, float | None, float | None, float | None, float | None
]

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
    """QE's lattice parameter ``alat`` in Å, from exactly one declared spelling.

    ``celldm(1)`` states alat in **Bohr**; ``A`` states it in **Å**. QE's documented
    contract is **"specify either, NOT both"** (INPUT_PW ``&system``/``ibrav``): declaring
    both is a QE-invalid combination and is refused (D190 — the reader never silently
    prefers one spelling, P4). Returns ``(None, None)`` when neither is declared, and the
    caller (the reader) refuses any alat-relative conversion rather than fabricate QE's
    1-Bohr default (**P3**). The note names the spelling used, so the resolution is never
    silent.
    """
    if celldm1 is not None and a is not None:
        raise ValueError(
            "both celldm(1) and A are declared — QE's documented contract is 'specify "
            "either, not both' (INPUT_PW &system ibrav); refusing rather than silently "
            "preferring one (D190)"
        )
    if a is not None:
        return float(a), "alat resolved from &system A (angstrom)."
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


# --- species labels (M50-S3; D191) ---------------------------------------------------


def species_symbol(label: str) -> tuple[str | None, str]:
    """QE's documented label → element rule: the element is the leading 1–2 characters of
    an ``ATOMIC_SPECIES`` label that form an element symbol, matched case-insensitively
    (the 2-character prefix is tried first, then the 1-character — so ``Fe1`` → Fe,
    ``O_vac`` → O, ``fe`` → Fe, and ``NaCl`` → Na, while ``Zz`` → None). Composes the
    shared ``normalize_symbol`` — the element table stays the single authority; only QE's
    *decoration* rule (labels are element symbols with optional trailing characters,
    per QE's documented ``ATOMIC_SPECIES`` convention) lives here, so M52's output parser
    resolves labels identically. Note that the reserved pseudo-element ``X`` (the schema's
    unknown-species marker) is a symbol in that table, so ``Xx`` resolves to the marker
    ``X`` (recorded), never to a real element. Returns ``(symbol, decoration)`` where
    ``decoration`` is the label's trailing characters beyond the matched prefix (``""``
    for a plain label) and ``(None, label)`` when no leading 1–2 characters form an
    element.
    """
    stripped = label.strip()
    for n in (2, 1):
        symbol = normalize_symbol(stripped[:n])
        if symbol is not None:
            return symbol, stripped[n:]
    return None, stripped


# --- ibrav expansion (M50-S2; D190) --------------------------------------------------


class UnsupportedIbravError(ValueError):
    """An ``ibrav`` value outside the hand-pinned supported set — the reader's
    ``QEIN_UNSUPPORTED_IBRAV``. A structured refusal, **never a guessed lattice** (P4)."""


#: QE's documented Bravais-lattice names (INPUT_PW v7.5 ``ibrav`` table) for the M50-S2
#: supported set. The set grows by corpus evidence (M53), not speculatively; 0 (the
#: explicit-cell path) is the reader's, not the expansion's.
IBRAV_NAMES: dict[int, str] = {
    1: "cubic P (sc)",
    2: "cubic F (fcc)",
    3: "cubic I (bcc)",
    4: "hexagonal P",
    6: "tetragonal P (st)",
    8: "orthorhombic P",
    12: "monoclinic P, unique axis c",
    -12: "monoclinic P, unique axis b",
    14: "triclinic P",
}

#: The INPUT_PW-documented vector formula per supported ibrav, for the derivation note.
_IBRAV_FORMULAS: dict[int, str] = {
    1: "v1=a(1,0,0), v2=a(0,1,0), v3=a(0,0,1)",
    2: "v1=(a/2)(-1,0,1), v2=(a/2)(0,1,1), v3=(a/2)(-1,1,0)",
    3: "v1=(a/2)(1,1,1), v2=(a/2)(-1,1,1), v3=(a/2)(-1,-1,1)",
    4: "v1=a(1,0,0), v2=a(-1/2,√3/2,0), v3=c(0,0,1)",
    6: "v1=a(1,0,0), v2=a(0,1,0), v3=c(0,0,1)",
    8: "v1=a(1,0,0), v2=b(0,1,0), v3=c(0,0,1)",
    12: "v1=a(1,0,0), v2=b(cosγ,sinγ,0), v3=c(0,0,1)",
    -12: "v1=a(1,0,0), v2=b(0,1,0), v3=c(cosβ,0,sinβ)",
    14: "v1=a(1,0,0), v2=b(cosγ,sinγ,0), "
    "v3=c(cosβ,(cosα−cosβcosγ)/sinγ,√(1+2cosαcosβcosγ−cos²α−cos²β−cos²γ)/sinγ)",
}

#: The ``abc2celldm`` angle mapping: which ``celldm(4..6)`` slot each declared
#: (cosAB, cosAC, cosBC) lands in, per ibrav (INPUT_PW v7.5; ``Modules/latgen.f90``
#: ``abc2celldm``). Slots absent from a value's map mean that angle is 90° (cosine 0).
_ABC_ANGLE_SLOTS: dict[int, dict[int, str]] = {
    12: {4: "ab"},  # unique axis c: only cos(ab) = gamma is free -> celldm(4)
    -12: {5: "ac"},  # unique axis b: only cos(ac) = beta is free -> celldm(5)
    14: {4: "bc", 5: "ac", 6: "ab"},  # triclinic: cos(bc)=α, cos(ac)=β, cos(ab)=γ
}


def lattice_from_ibrav(
    ibrav: int,
    *,
    celldm: Mapping[int, float] | None = None,
    abc: _AbcParams | None = None,
    alat: float,
) -> tuple[np.ndarray, str]:
    """The explicit ``cell.lattice_vectors`` (Å, rows a/b/c) for an ``ibrav ≠ 0`` input,
    following QE's documented conventions exactly (``latgen_lib``; INPUT_PW v7.5).

    ``celldm`` is the ``celldm(1..6)`` spelling (alat in Bohr, ``celldm(2)`` = b/a,
    ``celldm(3)`` = c/a, ``celldm(4..6)`` = cosines per ibrav); ``abc`` is the
    ``(A, B, C, cosAB, cosAC, cosBC)`` spelling (Å + cosines, mapped per ``abc2celldm``).
    **Exactly one spelling may be given** (QE: "specify either, NOT both") and both must
    reach identical vectors for the same lattice. ``alat`` is the resolved scale in Å (the
    reader owns the ``celldm(1)``/``A`` resolution via ``alat_angstrom``); it must be
    positive. Returns the 3×3 matrix plus the derivation note the reader records.

    Raises ``UnsupportedIbravError`` for a value outside the hand-pinned supported set
    (never a guessed lattice, P4), and ``ValueError`` for a malformed parameter set (the
    reader turns that into ``QEIN_MALFORMED_NAMELIST``).
    """
    if ibrav not in IBRAV_NAMES:
        raise UnsupportedIbravError(
            f"ibrav = {ibrav} is not in qe_pw_in's supported set "
            f"({', '.join(str(v) for v in sorted(IBRAV_NAMES, key=lambda v: (abs(v), v)))}; "
            "0 is the explicit-cell path): the hand-pinned Bravais expansions land per "
            "corpus evidence (M53), and the lattice is never guessed (P4)"
        )
    if celldm is not None and abc is not None:
        raise ValueError(
            "both celldm(1..6) and A,B,C,cosAB,cosAC,cosBC are declared — QE's documented "
            "contract is 'specify either, not both' (INPUT_PW &system ibrav)"
        )
    if celldm is None and abc is None:
        raise ValueError(
            "neither celldm(1..6) nor A,B,C,cosAB,cosAC,cosBC is declared — the ibrav "
            "expansion needs exactly one parameter spelling"
        )
    if alat <= 0:
        raise ValueError(f"the lattice scale alat must be positive, found {alat!r}")

    if celldm is not None:
        c2 = float(celldm.get(2, 0.0))
        c3 = float(celldm.get(3, 0.0))
        c4 = float(celldm.get(4, 0.0))
        c5 = float(celldm.get(5, 0.0))
        c6 = float(celldm.get(6, 0.0))
        spelling = f"celldm (celldm(1) = {celldm.get(1)!r} bohr)"
    else:
        assert abc is not None  # the neither-spelling refusal above already fired
        a, b, c, cosab, cosac, cosbc = abc
        if a is None:
            raise ValueError(
                "the A,B,C spelling is used but A is not declared — A is the lattice scale"
            )
        a = float(a)
        c2 = float(b) / a if b is not None else 0.0
        c3 = float(c) / a if c is not None else 0.0
        # The slots tell us which declared cosine lands where; everything else is 90°.
        declared = {"ab": cosab, "ac": cosac, "bc": cosbc}
        slots = _ABC_ANGLE_SLOTS.get(ibrav, {})
        c4 = c5 = c6 = 0.0
        for slot, key in slots.items():
            cosine = declared[key]
            if cosine is not None:
                if slot == 4:
                    c4 = float(cosine)
                elif slot == 5:
                    c5 = float(cosine)
                else:
                    c6 = float(cosine)
        spelling = f"A,B,C (A = {a!r} Å)"

    # Per-ibrav parameter requirements, mirroring QE's ``latgen_lib`` error checks.
    if ibrav in (4, 6) and c3 <= 0:
        raise ValueError(f"ibrav = {ibrav} requires c/a > 0 (celldm(3) or C/A) — found {c3!r}")
    if ibrav in (8, 12, -12, 14):
        if c2 <= 0:
            raise ValueError(f"ibrav = {ibrav} requires b/a > 0 (celldm(2) or B/A) — found {c2!r}")
        if c3 <= 0:
            raise ValueError(f"ibrav = {ibrav} requires c/a > 0 (celldm(3) or C/A) — found {c3!r}")
    if ibrav == 12 and abs(c4) >= 1:
        raise ValueError(f"ibrav = 12 requires |cos(γ)| < 1 (celldm(4) or cosAB) — found {c4!r}")
    if ibrav == -12 and abs(c5) >= 1:
        raise ValueError(f"ibrav = -12 requires |cos(β)| < 1 (celldm(5) or cosAC) — found {c5!r}")
    if ibrav == 14:
        if abs(c4) >= 1 or abs(c5) >= 1 or abs(c6) >= 1:
            raise ValueError(
                f"ibrav = 14 requires |cos| < 1 for all three angles (celldm(4..6) or "
                f"cosBC, cosAC, cosAB) — found ({c4!r}, {c5!r}, {c6!r})"
            )
        inner = 1 + 2 * c4 * c5 * c6 - c4**2 - c5**2 - c6**2
        if inner < 0:
            raise ValueError(
                f"ibrav = 14: the declared angles are inconsistent (QE latgen: 'celldm do "
                f"not make sense, check your data') — 1+2·cosα·cosβ·cosγ−cos²α−cos²β−cos²γ "
                f"= {inner!r} < 0"
            )

    # The unitless vector rows, exactly QE's ``latgen_lib`` formulas (all right-handed).
    if ibrav == 1:
        rows = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    elif ibrav == 2:
        t = 0.5
        rows = [[-t, 0.0, t], [0.0, t, t], [-t, t, 0.0]]
    elif ibrav == 3:
        t = 0.5
        rows = [[t, t, t], [-t, t, t], [-t, -t, t]]
    elif ibrav == 4:
        rows = [[1.0, 0.0, 0.0], [-0.5, math.sqrt(3.0) / 2.0, 0.0], [0.0, 0.0, c3]]
    elif ibrav == 6:
        rows = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, c3]]
    elif ibrav == 8:
        rows = [[1.0, 0.0, 0.0], [0.0, c2, 0.0], [0.0, 0.0, c3]]
    elif ibrav == 12:
        sen = math.sqrt(1.0 - c4**2)
        rows = [[1.0, 0.0, 0.0], [c2 * c4, c2 * sen, 0.0], [0.0, 0.0, c3]]
    elif ibrav == -12:
        sen = math.sqrt(1.0 - c5**2)
        rows = [[1.0, 0.0, 0.0], [0.0, c2, 0.0], [c3 * c5, 0.0, c3 * sen]]
    else:  # 14
        singam = math.sqrt(1.0 - c6**2)
        term = math.sqrt((1 + 2 * c4 * c5 * c6 - c4**2 - c5**2 - c6**2) / (1 - c6**2))
        rows = [
            [1.0, 0.0, 0.0],
            [c2 * c6, c2 * singam, 0.0],
            [c3 * c5, c3 * (c4 - c5 * c6) / singam, c3 * term],
        ]
    lattice = np.asarray(rows, dtype=float) * alat
    note = (
        f"lattice vectors derived from ibrav={ibrav} ({IBRAV_NAMES[ibrav]}) per QE's "
        f"documented conventions (INPUT_PW v7.5 / Modules/latgen.f90): {_IBRAV_FORMULAS[ibrav]}; "
        f"parameter spelling: {spelling}, alat = {alat!r} Å; the derivation is recorded — "
        "the explicit vectors are re-expressed, never guessed (P1/D190)."
    )
    return lattice, note
