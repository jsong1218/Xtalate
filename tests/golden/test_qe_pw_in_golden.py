"""qe_pw_in golden fidelity (v1.4 M50-S1/S2; Part 8 §3).

Each case's parse is diffed against its hand-verified ``expected.canonical.json``. The
expectations are external truth, not snapshots of parser output.

**S1 — the explicit-cell family** (``ibrav = 0`` + ``CELL_PARAMETERS``): every position is
hand-computed from the declared unit at the boundary — the angstrom case reads as-is, the
bohr case multiplies by QE's exact CODATA Bohr radius (0.52917720859 Å), the crystal case
maps fractional coordinates through the off-diagonal lattice, and the alat case scales by
the alat resolved from ``A`` — so a parser that guessed a scale, skipped a conversion, or
transposed the fractional→Cartesian multiply would fail here. All four share one
explicitly-declared, **off-diagonal** cell ((3,1,0)/(0,4,1)/(1,0,5)) so the crystal
mapping cannot hide a transpose behind an orthogonal lattice.

**S2 — the ibrav-expansion family** (``ibrav ≠ 0``, one hand-pinned case per supported
Bravais value): each expected 3×3 lattice is computed by hand from QE's documented
conventions (INPUT_PW v7.5 ``ibrav`` table; ``Modules/latgen.f90``) — the kBar→eV/Å³
discipline of v1.2 M42-S3 applied to lattice vectors — and the ``ibrav4-crystal`` cross
case pins the fractional→Cartesian conversion running against the *derived* lattice.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
from xtalate.sdk import ParseResult

GOLDEN = Path(__file__).parent / "qe_pw_in"

#: The S1 explicit-cell cases — one shared, explicitly-declared off-diagonal cell.
EXPLICIT_CASES = [
    "explicit-angstrom",
    "explicit-bohr-positions",
    "explicit-crystal-positions",
    "explicit-alat-positions",
]

#: The S2 ibrav-expansion cases — one per supported Bravais value, plus the cross case.
IBRAV_CASES = [
    "ibrav1-sc",
    "ibrav2-fcc",
    "ibrav3-bcc",
    "ibrav4-hex",
    "ibrav6-tetragonal",
    "ibrav8-orthorhombic",
    "ibrav12-monoclinic-c",
    "ibrav-12-monoclinic-b",
    "ibrav14-triclinic",
    "ibrav4-crystal",
]

CASES = EXPLICIT_CASES + IBRAV_CASES

#: The shared explicitly-declared cell every S1 golden carries (rows a, b, c, Å).
_CELL = [[3.0, 1.0, 0.0], [0.0, 4.0, 1.0], [1.0, 0.0, 5.0]]

#: Hand-computed expected lattice vectors (rows a/b/c, Å) per S2 case — the pinned truth.
_IBRAV_LATTICES: dict[str, list[list[float]]] = {
    "ibrav1-sc": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 4.0]],
    "ibrav2-fcc": [[-2.0, 0.0, 2.0], [0.0, 2.0, 2.0], [-2.0, 2.0, 0.0]],
    "ibrav3-bcc": [[2.0, 2.0, 2.0], [-2.0, 2.0, 2.0], [-2.0, -2.0, 2.0]],
    "ibrav4-hex": [[4.0, 0.0, 0.0], [-2.0, 3.4641016151377544, 0.0], [0.0, 0.0, 6.0]],
    "ibrav6-tetragonal": [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 6.0]],
    "ibrav8-orthorhombic": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 6.0]],
    "ibrav12-monoclinic-c": [[4.0, 0.0, 0.0], [1.25, 4.841229182759271, 0.0], [0.0, 0.0, 6.0]],
    "ibrav-12-monoclinic-b": [[4.0, 0.0, 0.0], [0.0, 5.0, 0.0], [1.5, 0.0, 5.809475019311126]],
    "ibrav14-triclinic": [[4.0, 0.0, 0.0], [3.0, 4.0, 0.0], [3.6, 0.0, 4.8]],
    # The cross case carries the same hex lattice as ibrav4-hex.
    "ibrav4-crystal": [[4.0, 0.0, 0.0], [-2.0, 3.4641016151377544, 0.0], [0.0, 0.0, 6.0]],
}


def _source(case: str) -> bytes:
    return (GOLDEN / case / "pw.in").read_bytes()


def _parse(case: str) -> ParseResult:
    return make_qe_pw_in_parser().parse(io.BytesIO(_source(case)), filename="pw.in")


@pytest.mark.parametrize("case", CASES)
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", EXPLICIT_CASES)
def test_golden_carries_the_declared_off_diagonal_lattice(case: str) -> None:
    obj = _parse(case).canonical
    frame = obj.frames[0]
    assert frame.cell is not None
    assert frame.cell.lattice_vectors.tolist() == _CELL
    assert frame.cell.pbc == (True, True, True)


@pytest.mark.parametrize("case", IBRAV_CASES)
def test_ibrav_golden_expands_to_the_hand_pinned_lattice(case: str) -> None:
    """Each ibrav case's 3×3 is the hand-computed exact value, and the derivation is
    recorded — the lattice is re-expressed, never guessed (P1/D190)."""
    obj = _parse(case).canonical
    frame = obj.frames[0]
    assert frame.cell is not None
    assert frame.cell.pbc == (True, True, True)
    got = frame.cell.lattice_vectors.tolist()
    assert got == [pytest.approx(row) for row in _IBRAV_LATTICES[case]]
    # The source encoding is recorded (the exact "ibrav=N" string is pinned in the
    # expected canonical; here we just assert the encoding family).
    assert obj.provenance.source_units["lattice_vectors"].startswith("ibrav=")
    notes = obj.provenance.parse_notes
    assert any("derived from ibrav" in note for note in notes)


def test_angstrom_golden_reads_positions_as_is() -> None:
    """The declared {angstrom} card is the identity boundary: Cartesian Å, read as-is."""
    obj = _parse("explicit-angstrom").canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 2.0, 3.0]
    assert obj.frames[0].atoms.symbols == ["Fe"]
    assert obj.provenance.source_units["positions"] == "angstrom"
    assert obj.provenance.original_coordinate_system == "cartesian"


def test_bohr_golden_converts_with_the_exact_qe_bohr_radius() -> None:
    """1.0 bohr must land at exactly QE's constant (0.52917720859 Å) — a wrong factor
    (e.g. the CODATA-2018 0.529177210903) would be a silent scale error."""
    obj = _parse("explicit-bohr-positions").canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [
        0.52917720859,
        0.52917720859,
        0.52917720859,
    ]
    assert obj.provenance.source_units["positions"] == "bohr"
    assert obj.provenance.original_coordinate_system == "cartesian"


def test_crystal_golden_maps_fractional_through_the_lattice() -> None:
    """(0.25, 0.25, 0.25) crystal against (3,1,0)/(0,4,1)/(1,0,5) is 0.25×(a+b+c) =
    (1.0, 1.25, 1.5) — off-diagonal, so a transpose or sign error cannot hide."""
    obj = _parse("explicit-crystal-positions").canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 1.25, 1.5]
    assert obj.provenance.source_units["positions"] == "crystal"
    assert obj.provenance.original_coordinate_system == "fractional"


def test_alat_golden_scales_by_alat_resolved_from_a() -> None:
    """0.25 alat with A = 4.0 Å must land at (1.0, 1.0, 1.0) — the resolved alat, never a
    guessed default."""
    obj = _parse("explicit-alat-positions").canonical
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 1.0, 1.0]
    assert obj.provenance.source_units["positions"] == "alat"
    assert obj.provenance.original_coordinate_system == "cartesian"
    assert any("alat resolved from &system A" in note for note in obj.provenance.parse_notes)


def test_ibrav_crystal_golden_converts_against_the_derived_lattice() -> None:
    """The S2 cross case: fractional coordinates convert against the *derived* hex
    lattice — 0.25·v1 + 0.25·v2 + 0.25·v3 = (0.5, √3/2, 1.5) Å (hand-pinned)."""
    obj = _parse("ibrav4-crystal").canonical
    assert obj.frames[0].atoms.positions[0].tolist() == pytest.approx(
        [0.5, 0.8660254037844386, 1.5]
    )
    assert obj.provenance.source_units["positions"] == "crystal"
    assert obj.provenance.original_coordinate_system == "fractional"


def test_no_ambiguous_scenario_fires_for_any_golden() -> None:
    """The plan's done-means #1: QE declares its units per card, so every conversion is
    deterministic — no ambiguous_units/ambiguous_* issue exists for a QE source (the VASP
    contrast, not the LAMMPS ambiguity)."""
    for case in CASES:
        result = _parse(case)
        assert result.issues == []
        assert all("ambiguous" not in issue.code.lower() for issue in result.issues)


def test_every_golden_records_the_conversion_in_parse_notes() -> None:
    """The conversion/derivation is never silent: each case's parse_notes name the per-card
    unit and what was done at the boundary (or the ibrav derivation, for S2 cases)."""
    for case in EXPLICIT_CASES:
        notes = _parse(case).canonical.provenance.parse_notes
        assert any("CELL_PARAMETERS" in note for note in notes)
        assert any("ATOMIC_POSITIONS" in note for note in notes)
    for case in IBRAV_CASES:
        notes = _parse(case).canonical.provenance.parse_notes
        assert any("derived from ibrav" in note for note in notes)
        assert any("ATOMIC_POSITIONS" in note for note in notes)
