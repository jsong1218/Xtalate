"""qe_pw_in golden fidelity (v1.4 M50-S1; Part 8 §3).

Each case's parse is diffed against its hand-verified ``expected.canonical.json``. The
expectations are external truth, not snapshots of parser output: every position is
hand-computed from the declared unit at the boundary — the angstrom case reads as-is, the
bohr case multiplies by QE's exact CODATA Bohr radius (0.52917720859 Å), the crystal case
maps fractional coordinates through the off-diagonal lattice, and the alat case scales by
the alat resolved from ``A`` — so a parser that guessed a scale, skipped a conversion, or
transposed the fractional→Cartesian multiply would fail here.

All four cases share one explicitly-declared, **off-diagonal** cell
((3,1,0)/(0,4,1)/(1,0,5)) so the crystal mapping cannot hide a transpose behind an
orthogonal lattice.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
from xtalate.sdk import ParseResult

GOLDEN = Path(__file__).parent / "qe_pw_in"
CASES = [
    "explicit-angstrom",
    "explicit-bohr-positions",
    "explicit-crystal-positions",
    "explicit-alat-positions",
]

#: The shared explicitly-declared cell every golden carries (rows a, b, c, Å).
_CELL = [[3.0, 1.0, 0.0], [0.0, 4.0, 1.0], [1.0, 0.0, 5.0]]


def _source(case: str) -> bytes:
    return (GOLDEN / case / "pw.in").read_bytes()


def _parse(case: str) -> ParseResult:
    return make_qe_pw_in_parser().parse(io.BytesIO(_source(case)), filename="pw.in")


@pytest.mark.parametrize("case", CASES)
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", CASES)
def test_golden_carries_the_declared_off_diagonal_lattice(case: str) -> None:
    obj = _parse(case).canonical
    frame = obj.frames[0]
    assert frame.cell is not None
    assert frame.cell.lattice_vectors.tolist() == _CELL
    assert frame.cell.pbc == (True, True, True)


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


def test_no_ambiguous_scenario_fires_for_any_golden() -> None:
    """The plan's done-means #1: QE declares its units per card, so every conversion is
    deterministic — no ambiguous_units/ambiguous_* issue exists for a QE source (the VASP
    contrast, not the LAMMPS ambiguity)."""
    for case in CASES:
        result = _parse(case)
        assert result.issues == []
        assert all("ambiguous" not in issue.code.lower() for issue in result.issues)


def test_every_golden_records_the_unit_conversion_in_parse_notes() -> None:
    """The conversion is never silent: each case's parse_notes name the per-card unit and
    what was done at the boundary."""
    for case in CASES:
        notes = _parse(case).canonical.provenance.parse_notes
        assert any("CELL_PARAMETERS" in note for note in notes)
        assert any("ATOMIC_POSITIONS" in note for note in notes)
