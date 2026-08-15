"""OUTCAR golden fidelity (v1.2 M43-S1; Part 8 §3).

Each case's parse is diffed against its hand-verified ``expected.canonical.json``. The expectations
are external truth, not snapshots of parser output: every position is a Cartesian coordinate read
as-is from the fixture's ``POSITION … TOTAL-FORCE`` table, every energy is the fixture's
``energy(sigma->0)`` value, and every stress is hand-derived from the ``in kB`` Voigt-6 line through
the exact kBar→eV/Å³ sign flip (D161) — so a parser that guessed a stress sign, re-ran the
fractional→Cartesian multiply, or reused the initial cell would fail here.

The streamed reading must match the *same* external-truth expectation the whole-file one does
(``parse`` is defined through ``parse_stream``, so this pins the D56 one-code-path guarantee against
truth, not merely against itself).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers.outcar import make_outcar_parser
from xtalate.sdk import ParseResult
from xtalate.sdk.streaming import materialize

GOLDEN = Path(__file__).parent / "outcar"
CASES = ["relax-h2o", "md-h2o", "npt-h2o"]


def _source(case: str) -> bytes:
    return (GOLDEN / case / "OUTCAR").read_bytes()


def _parse(case: str) -> ParseResult:
    return make_outcar_parser().parse(io.BytesIO(_source(case)), filename="OUTCAR")


@pytest.mark.parametrize("case", CASES)
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", CASES)
def test_streamed_parse_matches_golden(case: str) -> None:
    """The streamed reading must match the *same* external-truth expectation the whole-file one
    does — not merely match the whole-file reading (which would be self-consistent by construction,
    since ``parse`` is defined through ``parse_stream``)."""
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    stream = make_outcar_parser().parse_stream(io.BytesIO(_source(case)), filename="OUTCAR")
    obj, _ = materialize(stream)
    assert_matches_golden(obj, expected)


@pytest.mark.parametrize("case", CASES)
def test_multi_step_goldens_carry_a_trajectory_without_a_timestep(case: str) -> None:
    obj = _parse(case).canonical
    assert obj.trajectory is not None
    assert obj.trajectory.timestep is None


def test_relax_golden_would_catch_a_parser_reusing_the_initial_positions() -> None:
    """The relaxation fixture pins per-step geometry: the first H atom must move 7.5 -> 7.3 -> 7.4 Å
    against the fixed cell. A parser that reused the initial positions would silently freeze it."""
    obj = _parse("relax-h2o").canonical
    h0 = [frame.atoms.positions[0].tolist() for frame in obj.frames]
    assert h0 == [[5.0, 7.5, 5.0], [5.0, 7.3, 5.0], [5.0, 7.4, 5.0]]


def test_npt_golden_would_catch_a_parser_reusing_the_initial_lattice() -> None:
    """The NpT fixture's whole reason to exist: per-step cells 10.0 -> 10.1 -> 10.2 Å. A parser that
    read only the header's initial lattice would silently keep every frame at 10.0 Å."""
    obj = _parse("npt-h2o").canonical
    cells = []
    for frame in obj.frames:
        assert frame.cell is not None
        cells.append(frame.cell.lattice_vectors[0][0])
    assert cells == [10.0, 10.1, 10.2]


def test_md_golden_pins_stress_absence_not_a_zero_tensor() -> None:
    """The MD run carries no stress block; a stress-less step must read None, never a defaulted zero
    tensor (P3) — the OUTCAR counterpart of the vasprun SCF golden."""
    obj = _parse("md-h2o").canonical
    assert all(frame.electronic.stress is None for frame in obj.frames)


def test_relax_golden_pins_the_vasp_voigt_off_diagonal_ordering() -> None:
    """The 'in kB' line is 1602.1766208 × [1, 2, 0.5, 0.25, 0.125, 0.0625] (VASP Voigt order
    [XX, YY, ZZ, XY, YZ, ZX]); the mapped tension-positive tensor must place XY at [0][1],
    YZ at [1][2] and ZX at [0][2] — a wrong Voigt ordering (e.g. ASE's) would silently transpose
    the off-diagonal components (D161)."""
    stress = _parse("relax-h2o").canonical.frames[0].electronic.stress
    assert stress is not None
    assert stress.tolist() == [
        [-1.0, -0.25, -0.0625],
        [-0.25, -2.0, -0.125],
        [-0.0625, -0.125, -0.5],
    ]
