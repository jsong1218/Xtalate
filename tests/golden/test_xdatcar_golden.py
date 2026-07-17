"""XDATCAR golden fidelity (M13 deliverable 4; Part 8 §3).

Each case's parse is diffed against its hand-verified ``expected.canonical.json``. The
expectations are external truth, not a snapshot of parser output: every fractional coordinate
in the fixtures is an exact binary fraction against a cubic cell, so each Cartesian value was
derived by hand first and the file only records it.

The identity round-trip runs **through the streaming path** (the M13 "done means"), which is
also what pins the claim that streaming and whole-file readings agree on real fixtures rather
than only on the synthetic cases in the unit tests.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.exporters.xdatcar import make_xdatcar_exporter
from xtalate.parsers.xdatcar import make_xdatcar_parser
from xtalate.schema import CanonicalObject
from xtalate.sdk.streaming import materialize

GOLDEN = Path(__file__).parent / "xdatcar"
CASES = ["nacl-md-fixed-cell", "si-npt-variable-cell", "si-single-configuration"]


def _source(case: str) -> bytes:
    return (GOLDEN / case / "XDATCAR").read_bytes()


def _parse(case: str) -> CanonicalObject:
    return make_xdatcar_parser().parse(io.BytesIO(_source(case)), filename="XDATCAR").canonical


@pytest.mark.parametrize("case", CASES)
def test_parse_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_parse(case), expected)


@pytest.mark.parametrize("case", CASES)
def test_streamed_parse_matches_golden(case: str) -> None:
    """The streamed reading must match the *same* external-truth expectation the whole-file one
    does — not merely match the whole-file reading (which would be self-consistent by
    construction, since ``parse`` is defined through ``parse_stream``)."""
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    stream = make_xdatcar_parser().parse_stream(io.BytesIO(_source(case)), filename="XDATCAR")
    obj, _ = materialize(stream)
    assert_matches_golden(obj, expected)


@pytest.mark.parametrize("case", CASES)
def test_identity_roundtrip_through_the_streaming_path(case: str) -> None:
    """XDATCAR → Canonical → XDATCAR → Canonical′ agrees on all scientific content."""
    original = _parse(case)
    buf = io.BytesIO()
    make_xdatcar_exporter().export(original, buf)
    back = make_xdatcar_parser().parse(io.BytesIO(buf.getvalue()), filename="XDATCAR").canonical
    # Positions cross a lattice inversion on write (XDATCAR is a Direct format), so they agree to
    # float64 rounding rather than bit-for-bit — the bound the exporter declares in lossy_notes.
    for a, b in zip(original.frames, back.frames, strict=True):
        np.testing.assert_allclose(a.atoms.positions, b.atoms.positions, atol=1e-12)
        assert a.atoms.symbols == b.atoms.symbols
        assert a.cell is not None and b.cell is not None
        np.testing.assert_allclose(a.cell.lattice_vectors, b.cell.lattice_vectors)
        assert a.cell.pbc == b.cell.pbc
    assert back.trajectory == original.trajectory
    assert back.user_metadata.custom_global == original.user_metadata.custom_global


def test_npt_golden_would_catch_a_parser_reusing_frame_zeros_lattice() -> None:
    """The NpT fixture's whole reason to exist, asserted directly: identical Direct coordinates
    under a growing cell must give *different* Cartesian positions. A parser that read only the
    first header would place every atom after frame 0 wrongly, and silently."""
    obj = _parse("si-npt-variable-cell")
    second_atom = [frame.atoms.positions[1].tolist() for frame in obj.frames]
    assert second_atom == [[2.8, 2.8, 2.8], [2.9, 2.9, 2.9], [3.0, 3.0, 3.0]]


def test_single_configuration_golden_is_a_structure_not_a_trajectory() -> None:
    assert _parse("si-single-configuration").trajectory is None


def test_multi_configuration_goldens_carry_a_trajectory_without_a_timestep() -> None:
    for case in ["nacl-md-fixed-cell", "si-npt-variable-cell"]:
        obj = _parse(case)
        assert obj.trajectory is not None
        assert obj.trajectory.timestep is None
