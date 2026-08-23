"""The pw.x input↔output echo cross-check (v1.4 M52-S1; standing rule 4).

One synthetic run is authored as *both* a pw.x input and its pw.x output (the output's setup
echo repeats the input's cell / species / positions), then read by the **M50 input parser**
(``qe_pw_in``) and the **M52 output parser** (``qe_pw_out``) and asserted to agree on the
shared initial structure — ``cell.lattice_vectors``, ``atoms.symbols``, ``atoms.positions``.

This is the milestone's central correctness proof: a silent unit or sign disagreement between
the two QE readers of one calculation is the exact bug that poisons an MLIP training set at
scale, and the shared ``_qe`` core exists so QE's conventions are discovered once. The 7.x
rendering of the output is byte-for-byte the committed ``relax`` golden; S2 adds the 6.x
rendering of the same run (the go/no-go gate).

**What the cross-check exercises:** the alat resolution (input from ``celldm(1)``, output from
the ``lattice parameter (alat)`` line — both must land 5.0 Å), the bohr→Å boundary (input
``ATOMIC_POSITIONS {bohr}``, output ``positions (bohr units)`` site table), and the per-step
angstrom positions cards (output only) that must reproduce the same initial configuration.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests.parsers._qe_run import render_pw_in, render_pw_out
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
from xtalate.parsers.qe_pw_out import make_qe_pw_out_parser
from xtalate.schema import CanonicalObject

_GOLDEN_RELAX = Path(__file__).parent.parent / "golden" / "qe_pw_out" / "relax" / "pw.out"


def _parse_input() -> CanonicalObject:
    return (
        make_qe_pw_in_parser()
        .parse(io.BytesIO(render_pw_in().encode()), filename="pw.in")
        .canonical
    )


def _parse_output(layout: str) -> CanonicalObject:
    return (
        make_qe_pw_out_parser()
        .parse(io.BytesIO(render_pw_out(layout).encode()), filename="pw.out")
        .canonical
    )


def _assert_shared_structure_agrees(
    input_obj: CanonicalObject, output_obj: CanonicalObject
) -> None:
    fin, fout = input_obj.frames[0], output_obj.frames[0]
    # Species: the input resolves ATOMIC_SPECIES labels; the output resolves the site-table
    # labels — both must land the same per-atom symbols.
    assert fin.atoms.symbols == fout.atoms.symbols == ["O", "H", "H"]
    # The initial cell: input celldm(1)-derived alat × identity == output crystal-axes × alat.
    assert fin.cell is not None and fout.cell is not None
    np.testing.assert_allclose(fin.cell.lattice_vectors, fout.cell.lattice_vectors, atol=1e-9)
    assert fin.cell.pbc == fout.cell.pbc == (True, True, True)
    # The initial configuration: input bohr positions converted at the boundary == output
    # (frame 0 reuses the initial configuration; its angstrom card reproduces it).
    np.testing.assert_allclose(fin.atoms.positions, fout.atoms.positions, atol=1e-9)


def test_the_output_rendering_is_byte_for_byte_the_committed_golden() -> None:
    """The cross-check and the golden share one source of truth — a drift between them would
    mean the golden and the rule-4 guard are no longer the same run."""
    assert render_pw_out("7x").encode() == _GOLDEN_RELAX.read_bytes()


@pytest.mark.parametrize("layout", ["7x"])
def test_input_and_output_parsers_agree_on_the_initial_structure(layout: str) -> None:
    _assert_shared_structure_agrees(_parse_input(), _parse_output(layout))


def test_input_parser_parse_is_warning_free() -> None:
    """The cross-check input bare-parses without recovery or warnings (the matrix source
    discipline — nothing about the shared structure needs a preset)."""
    result = make_qe_pw_in_parser().parse(io.BytesIO(render_pw_in().encode()), filename="pw.in")
    assert result.issues == []


def test_output_parser_lands_the_hand_pinned_initial_values() -> None:
    """The cross-check is only meaningful because both sides land the same hand-verifiable
    values: 5.0 Å cell, O at the cell centre, H at 3.25 Å on the x/y axes."""
    obj = _parse_output("7x")
    assert obj.frames[0].cell is not None
    np.testing.assert_allclose(
        obj.frames[0].cell.lattice_vectors, [[5.0, 0, 0], [0, 5.0, 0], [0, 0, 5.0]], atol=1e-9
    )
    np.testing.assert_allclose(
        obj.frames[0].atoms.positions,
        [[2.5, 2.5, 2.5], [3.25, 2.5, 2.5], [2.5, 3.25, 2.5]],
        atol=1e-9,
    )
