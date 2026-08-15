"""The OUTCAR↔vasprun cross-check (v1.2 M43-S1/S2; standing rule 4).

One synthetic run is authored as *both* an OUTCAR and a vasprun.xml (classical layout) from a single
source of truth, then read by both parsers and asserted to agree per step on
energy/forces/stress/positions/cell. S2 runs the cross-check for **both** VASP major layouts — the
5.x and 6.x OUTCAR spellings of the same run — and asserts the two layouts agree with the
vasprun.xml golden (and with each other): this is the milestone's go/no-go gate. A stress-sign or
positions-mode disagreement between any two readers of one run is the silent MLIP-scale bug standing
rule 4 exists to prevent, and the shared ``_vasp`` core exists so the mapping is discovered once —
this test is the guard that the three *spellings* (Cartesian + ``in kB`` Voigt-6 in two column
layouts, vs direct + 3×3 kBar varray) map back to the same canonical values.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from tests.parsers._vasp_run import H2O_RUN, render_outcar, render_vasprun
from xtalate.parsers.outcar import make_outcar_parser
from xtalate.parsers.vasprun import make_vasprun_parser
from xtalate.schema import CanonicalObject


def _assert_close(a: np.ndarray | None, b: np.ndarray | None) -> None:
    assert (a is None) == (b is None)
    if a is not None and b is not None:
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12)


def _parse_outcar(layout: str) -> CanonicalObject:
    return (
        make_outcar_parser()
        .parse(io.BytesIO(render_outcar(H2O_RUN, layout=layout).encode()), filename="OUTCAR")
        .canonical
    )


def _parse_vasprun() -> CanonicalObject:
    return (
        make_vasprun_parser()
        .parse(io.BytesIO(render_vasprun(H2O_RUN).encode()), filename="vasprun.xml")
        .canonical
    )


def _assert_frames_agree(a: CanonicalObject, b: CanonicalObject) -> None:
    assert len(a.frames) == len(b.frames) == 3
    for fa, fb in zip(a.frames, b.frames, strict=True):
        assert fa.index == fb.index
        assert fa.atoms.symbols == fb.atoms.symbols
        # energy(sigma->0) (OUTCAR) == e_0_energy (vasprun) — the same physical quantity.
        assert fa.electronic.total_energy == fb.electronic.total_energy
        # Positions: OUTCAR reads Cartesian as-is; vasprun reads direct and multiplies by the cell.
        _assert_close(fa.atoms.positions, fb.atoms.positions)
        # Forces verbatim in both.
        _assert_close(fa.dynamics.forces, fb.dynamics.forces)
        # Stress: the M43 trap — the 'in kB' Voigt-6 line and the 3×3 kBar varray must agree, sign
        # and Voigt ordering included.
        _assert_close(fa.electronic.stress, fb.electronic.stress)
        # Cell: the fixed-cell form (same 10 Å lattice every step).
        assert fa.cell is not None
        assert fb.cell is not None
        _assert_close(fa.cell.lattice_vectors, fb.cell.lattice_vectors)


@pytest.mark.parametrize("layout", ["6x", "5x"])
def test_outcar_and_vasprun_agree_per_step(layout: str) -> None:
    _assert_frames_agree(_parse_outcar(layout), _parse_vasprun())


def test_both_outcar_layouts_agree_with_each_other() -> None:
    """The 5.x and 6.x spellings of one run must agree with *each other*, not merely with vasprun —
    a column-drift bug that happened to cancel against a vasprun bug would otherwise pass."""
    _assert_frames_agree(_parse_outcar("6x"), _parse_outcar("5x"))


def test_stress_sign_and_voigt_ordering_pinned_by_the_cross_check() -> None:
    """The cross-check is only green if *both* readers produce the same tension-positive tensor; a
    sign flip or a Voigt-ordering transpose on either side would diverge here."""
    expected = [[-1.0, -0.25, -0.0625], [-0.25, -2.0, -0.125], [-0.0625, -0.125, -0.5]]
    for layout in ("6x", "5x"):
        outcar = _parse_outcar(layout)
        vasprun = _parse_vasprun()
        assert outcar.frames[0].electronic.stress is not None
        assert vasprun.frames[0].electronic.stress is not None
        np.testing.assert_allclose(outcar.frames[0].electronic.stress, expected)
        np.testing.assert_allclose(vasprun.frames[0].electronic.stress, expected)


def test_stress_absence_agrees_between_the_two_readers() -> None:
    for layout in ("6x", "5x"):
        outcar = _parse_outcar(layout)
        vasprun = _parse_vasprun()
        assert outcar.frames[1].electronic.stress is None
        assert vasprun.frames[1].electronic.stress is None
