"""vasprun.xml golden fidelity (v1.2 M42-S2; Part 8 §3).

Each case's parse is diffed against its hand-verified ``expected.canonical.json``. The
expectations are external truth, not snapshots of parser output: every direct coordinate in
the fixtures multiplies a simple cubic lattice (0.5 × a halves an exponent), so each
Cartesian value was derived by hand first and the file only records it; the energies and
forces are verbatim from the fixture's ``<energy>``/``<varray name="forces">`` blocks.

The streamed reading must match the *same* external-truth expectation the whole-file one
does (``parse`` is defined through ``parse_stream``, so this pins the D56 one-code-path
guarantee against truth, not merely against itself).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers.vasprun import make_vasprun_parser
from xtalate.sdk import ParseResult
from xtalate.sdk.streaming import materialize

GOLDEN = Path(__file__).parent / "vasprun"
CASES = ["scf-h2o", "relax-h2o", "si-npt-per-step-cell"]


def _source(case: str) -> bytes:
    return (GOLDEN / case / "vasprun.xml").read_bytes()


def _parse(case: str) -> ParseResult:
    return make_vasprun_parser().parse(io.BytesIO(_source(case)), filename="vasprun.xml")


@pytest.mark.parametrize("case", CASES)
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case).canonical, expected)


@pytest.mark.parametrize("case", CASES)
def test_streamed_parse_matches_golden(case: str) -> None:
    """The streamed reading must match the *same* external-truth expectation the whole-file one
    does — not merely match the whole-file reading (which would be self-consistent by
    construction, since ``parse`` is defined through ``parse_stream``)."""
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    stream = make_vasprun_parser().parse_stream(io.BytesIO(_source(case)), filename="vasprun.xml")
    obj, _ = materialize(stream)
    assert_matches_golden(obj, expected)


def test_single_configuration_golden_is_a_structure_not_a_trajectory() -> None:
    assert _parse("scf-h2o").canonical.trajectory is None


def test_multi_step_goldens_carry_a_trajectory_without_a_timestep() -> None:
    for case in ["relax-h2o", "si-npt-per-step-cell"]:
        obj = _parse(case).canonical
        assert obj.trajectory is not None
        assert obj.trajectory.timestep is None


def test_npt_golden_would_catch_a_parser_reusing_the_initial_lattice() -> None:
    """The NpT fixture's whole reason to exist: identical direct coordinates under a growing
    cell must give *different* Cartesian positions. A parser that read only the initial
    structure's lattice would place every step's second atom at 2.8 Å, silently."""
    obj = _parse("si-npt-per-step-cell").canonical
    second_atom = [frame.atoms.positions[1].tolist() for frame in obj.frames]
    assert second_atom == [[2.8, 2.8, 2.8], [2.9, 2.9, 2.9], [3.0, 3.0, 3.0]]


def test_relax_golden_would_catch_a_parser_reusing_the_initial_positions() -> None:
    """The relaxation fixture pins per-step geometry: each <calculation> carries its own
    <structure>, so the H atoms must move 7.5 -> 7.3 -> 7.4 -> 7.45 Å against the fixed cell.
    A parser that reused the initial structure for every step would silently freeze them at
    7.5 Å."""
    obj = _parse("relax-h2o").canonical
    h1 = [frame.atoms.positions[1].tolist() for frame in obj.frames]
    assert h1 == [[5.0, 7.3, 5.0], [5.0, 7.4, 5.0], [5.0, 7.45, 5.0]]
