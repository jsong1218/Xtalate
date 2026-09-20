"""H5MD exporter tests (v2.0 M74).

S1 pins the exporter's variable-N write mechanism against a round-trip fixture: a genuine
grand-canonical trajectory (frame 0 has 2 atoms, frame 1 has 3) must survive
export → re-parse within tolerance, proving the M72/M73 variable-N engines on a real binary
container before any of the richer field mapping is built (the go/no-go).
"""

from __future__ import annotations

from io import BytesIO

import numpy as np

from xtalate.exporters.h5md import H5MDExporter
from xtalate.parsers.h5md import H5MDParser
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    Provenance,
    TrajectoryMetadata,
)


def _variable_n_object() -> CanonicalObject:
    # Grand-canonical: frame 0 has 2 atoms, frame 1 has 3 (a real variable-N trajectory).
    cell = Cell(
        lattice_vectors=np.array([[10.0, 0, 0], [0, 10, 0], [0, 0, 10]]), pbc=(True, True, True)
    )
    f0 = Frame(
        index=0,
        atoms=AtomsBlock(symbols=["H", "O"], positions=np.array([[0.0, 0, 0], [0, 0, 1.0]])),
        cell=cell,
    )
    f1 = Frame(
        index=1,
        atoms=AtomsBlock(
            symbols=["H", "O", "H"],
            positions=np.array([[0.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]]),
        ),
        cell=cell,
    )
    provenance = Provenance(
        source_filename=None,
        source_format="h5md",
        original_coordinate_system="cartesian",
    )
    return CanonicalObject(
        frames=[f0, f1], trajectory=TrajectoryMetadata(timestep=None), provenance=provenance
    )


def test_variable_n_h5md_round_trips_within_tolerance() -> None:
    src = _variable_n_object()
    buf = BytesIO()
    H5MDExporter().export(src, buf)
    buf.seek(0)
    result = H5MDParser().parse(buf, filename="rt.h5")
    obj = result.canonical
    assert [len(fr.atoms.atomic_numbers) for fr in obj.frames] == [2, 3]
    np.testing.assert_allclose(
        obj.frames[1].atoms.positions,
        np.array([[0.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]]),
        atol=1e-8,
    )
    assert obj.frames[0].atoms.atomic_numbers == [1, 8]
    assert obj.frames[1].atoms.atomic_numbers == [1, 8, 1]
