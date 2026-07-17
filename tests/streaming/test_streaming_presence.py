"""The streaming ``PresenceAccumulator`` reproduces ``compute_field_presence`` exactly (M12,
deliverable 2; standing rule 3). Any divergence is a stop-the-line bug, so these tests pin the
identity across the tricky cases: uniform present/absent, ``mixed`` per-frame fields, root metadata,
and the three dynamic custom namespaces."""

from __future__ import annotations

import numpy as np
import pytest

from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    PresenceAccumulator,
    Provenance,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.sdk.streaming import stream_of


def _accumulate(obj: CanonicalObject) -> object:
    stream = stream_of(obj)
    acc = PresenceAccumulator(obj.schema_version)
    h = stream.header
    acc.observe_header(
        trajectory=h.trajectory,
        simulation=h.simulation,
        tags=h.tags,
        annotations=h.annotations,
        custom_global=h.custom_global,
        custom_per_atom=h.custom_per_atom,
    )
    for sf in stream.frames():
        keys = [k for k, v in sf.per_frame_custom.items() if v is not None]
        acc.observe_frame(sf.frame, keys)
    return acc.result()


def _frame(i: int, *, cell: bool = False, vel: bool = False, energy: bool = False) -> Frame:
    return Frame(
        index=i,
        atoms=AtomsBlock(symbols=["O", "H"], positions=np.array([[0.0, 0, 0], [1, 0, 0]])),
        cell=Cell(lattice_vectors=np.eye(3) * 5, pbc=(True, True, True)) if cell else None,
        dynamics=Dynamics(velocities=np.zeros((2, 3)) if vel else None),
        electronic=Electronic(total_energy=-1.0 if energy else None),
    )


def _prov() -> Provenance:
    return Provenance(
        source_filename=None, source_format="extxyz", original_coordinate_system="cartesian"
    )


CASES = {
    "single_minimal": CanonicalObject(frames=[_frame(0)], provenance=_prov()),
    "uniform_cell_energy": CanonicalObject(
        frames=[_frame(0, cell=True, energy=True), _frame(1, cell=True, energy=True)],
        trajectory=TrajectoryMetadata(timestep=None),
        provenance=_prov(),
    ),
    "mixed_cell": CanonicalObject(
        frames=[_frame(0, cell=True), _frame(1), _frame(2, cell=True, vel=True)],
        trajectory=TrajectoryMetadata(timestep=None),
        provenance=_prov(),
    ),
    "rich_metadata": CanonicalObject(
        frames=[_frame(0), _frame(1)],
        trajectory=TrajectoryMetadata(timestep=None),
        simulation=SimulationMetadata(source_code="vasp", temperature=300.0),
        provenance=_prov(),
        user_metadata=UserMetadata(
            tags=["md"],
            annotations={"note": "x"},
            custom_global={"g": 1},
            custom_per_atom={"lab": ["x", "y"]},
            custom_per_frame={"c": [1, None]},
        ),
    ),
}


@pytest.mark.parametrize("name", list(CASES))
def test_accumulator_matches_compute_field_presence(name: str) -> None:
    obj = CASES[name]
    want = obj.field_presence().model_dump(mode="json")
    got = _accumulate(obj).model_dump(mode="json")  # type: ignore[attr-defined]
    assert got == want
