"""The OUTCAR↔vasprun cross-check (v1.2 M43-S1; standing rule 4).

One synthetic run is authored as *both* an OUTCAR (VASP 6.x layout) and a vasprun.xml (classical
layout) from a single source of truth, then read by both parsers and asserted to agree per step on
energy/forces/stress/positions/cell. This is the milestone's central correctness proof: a
stress-sign
or positions-mode disagreement between the two readers of one run is the silent MLIP-scale bug
standing rule 4 exists to prevent, and the shared ``_vasp`` core exists so the mapping is discovered
once — this test is the guard that the two *spellings* (Cartesian + ``in kB`` Voigt-6 vs direct +
3×3 kBar varray) map back to the same canonical values.
"""

from __future__ import annotations

import io

import numpy as np

from tests.parsers._vasp_run import H2O_RUN, render_outcar, render_vasprun
from xtalate.parsers.outcar import make_outcar_parser
from xtalate.parsers.vasprun import make_vasprun_parser


def _assert_close(a: np.ndarray | None, b: np.ndarray | None) -> None:
    assert (a is None) == (b is None)
    if a is not None and b is not None:
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12)


def test_outcar_and_vasprun_agree_per_step() -> None:
    outcar = (
        make_outcar_parser()
        .parse(io.BytesIO(render_outcar(H2O_RUN).encode()), filename="OUTCAR")
        .canonical
    )
    vasprun = (
        make_vasprun_parser()
        .parse(io.BytesIO(render_vasprun(H2O_RUN).encode()), filename="vasprun.xml")
        .canonical
    )

    assert len(outcar.frames) == len(vasprun.frames) == 3

    for a, b in zip(outcar.frames, vasprun.frames, strict=True):
        assert a.index == b.index
        assert a.atoms.symbols == b.atoms.symbols
        # energy(sigma->0) (OUTCAR) == e_0_energy (vasprun) — the same physical quantity.
        assert a.electronic.total_energy == b.electronic.total_energy
        # Positions: OUTCAR reads Cartesian as-is; vasprun reads direct and multiplies by the cell.
        _assert_close(a.atoms.positions, b.atoms.positions)
        # Forces verbatim in both.
        _assert_close(a.dynamics.forces, b.dynamics.forces)
        # Stress: the M43 trap — the 'in kB' Voigt-6 line and the 3×3 kBar varray must agree, sign
        # and Voigt ordering included.
        _assert_close(a.electronic.stress, b.electronic.stress)
        # Cell: the fixed-cell form (same 10 Å lattice every step).
        assert a.cell is not None
        assert b.cell is not None
        _assert_close(a.cell.lattice_vectors, b.cell.lattice_vectors)


def test_stress_sign_and_voigt_ordering_pinned_by_the_cross_check() -> None:
    """The cross-check is only green if *both* readers produce the same tension-positive tensor; a
    sign flip or a Voigt-ordering transpose on either side would diverge here."""
    outcar = (
        make_outcar_parser()
        .parse(io.BytesIO(render_outcar(H2O_RUN).encode()), filename="OUTCAR")
        .canonical
    )
    vasprun = (
        make_vasprun_parser()
        .parse(io.BytesIO(render_vasprun(H2O_RUN).encode()), filename="vasprun.xml")
        .canonical
    )
    expected = [[-1.0, -0.25, -0.0625], [-0.25, -2.0, -0.125], [-0.0625, -0.125, -0.5]]
    assert outcar.frames[0].electronic.stress is not None
    assert vasprun.frames[0].electronic.stress is not None
    np.testing.assert_allclose(outcar.frames[0].electronic.stress, expected)
    np.testing.assert_allclose(vasprun.frames[0].electronic.stress, expected)


def test_stress_absence_agrees_between_the_two_readers() -> None:
    outcar = (
        make_outcar_parser()
        .parse(io.BytesIO(render_outcar(H2O_RUN).encode()), filename="OUTCAR")
        .canonical
    )
    vasprun = (
        make_vasprun_parser()
        .parse(io.BytesIO(render_vasprun(H2O_RUN).encode()), filename="vasprun.xml")
        .canonical
    )
    assert outcar.frames[1].electronic.stress is None
    assert vasprun.frames[1].electronic.stress is None
