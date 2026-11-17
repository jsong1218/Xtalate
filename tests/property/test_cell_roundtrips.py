"""Property tests: fractional/Cartesian inversion and cell parameters through the writers."""

from __future__ import annotations

import io

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from tests.property._strategies import _lattice
from xtalate.exporters.cif import make_cif_exporter
from xtalate.exporters.poscar import make_poscar_exporter
from xtalate.parsers._common import build_provenance
from xtalate.parsers.cif import make_cif_parser
from xtalate.parsers.poscar import make_poscar_parser
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame
from xtalate.schema.cell import cell_parameters, to_cartesian, to_fractional

_FRAC = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)


@given(
    lattice=_lattice(),
    frac=st.lists(st.tuples(_FRAC, _FRAC, _FRAC), min_size=1, max_size=8),
)
def test_fractional_cartesian_round_trip(
    lattice: list[list[float]], frac: list[tuple[float, float, float]]
) -> None:
    lat = np.asarray(lattice, dtype=np.float64)
    fractional = np.asarray(frac, dtype=np.float64)
    back = to_fractional(to_cartesian(fractional, lat), lat)
    np.testing.assert_allclose(back, fractional, atol=1e-8, rtol=1e-8)


def _object(lattice: list[list[float]]) -> CanonicalObject:
    lat = np.asarray(lattice, dtype=np.float64)
    frac = np.array([[0.1, 0.2, 0.3], [0.6, 0.5, 0.4]])
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=["Si", "O"], positions=to_cartesian(frac, lat)),
                cell=Cell(lattice_vectors=lat, pbc=(True, True, True)),
            )
        ],
        provenance=build_provenance(
            format_id="test",
            filename=None,
            original_coordinate_system="cartesian",
            source_units={},
            parse_notes=[],
        ),
    )


def _assert_same_cell_parameters(
    lattice: list[list[float]], got: np.ndarray, *, length_rtol: float, angle_atol: float
) -> None:
    (a0, b0, c0), (al0, be0, ga0) = cell_parameters(np.asarray(lattice, dtype=np.float64))
    (a1, b1, c1), (al1, be1, ga1) = cell_parameters(got)
    np.testing.assert_allclose([a1, b1, c1], [a0, b0, c0], rtol=length_rtol)
    np.testing.assert_allclose([al1, be1, ga1], [al0, be0, ga0], atol=angle_atol)


@given(lattice=_lattice())
def test_poscar_write_read_preserves_cell_parameters(lattice: list[list[float]]) -> None:
    buf = io.BytesIO()
    make_poscar_exporter().export(_object(lattice), buf)
    buf.seek(0)
    cell = make_poscar_parser().parse(buf, filename="POSCAR").canonical.frames[0].cell
    assert cell is not None
    _assert_same_cell_parameters(lattice, cell.lattice_vectors, length_rtol=1e-9, angle_atol=1e-7)


@given(lattice=_lattice())
def test_cif_write_read_preserves_cell_parameters(lattice: list[list[float]]) -> None:
    buf = io.BytesIO()
    make_cif_exporter().export(_object(lattice), buf)
    buf.seek(0)
    cell = make_cif_parser().parse(buf, filename=None).canonical.frames[0].cell
    assert cell is not None
    _assert_same_cell_parameters(lattice, cell.lattice_vectors, length_rtol=1e-9, angle_atol=1e-7)
