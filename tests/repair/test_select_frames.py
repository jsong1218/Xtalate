"""select_frames — the selective-reductive trajectory-subsampling repair (QoL Q2)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from xtalate.repair import (
    SELECTIVE_REDUCTIVE_HAZARD,
    RepairError,
    RepairRequest,
    apply_repairs,
    get_operation,
)
from xtalate.repair.contract import REPAIR_BLOCK_EMPTY_SELECTION
from xtalate.repair.operations import SelectFrames
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Frame,
    Provenance,
    TrajectoryMetadata,
    UserMetadata,
)


def _trajectory(n_frames: int, *, with_per_frame: bool = True) -> CanonicalObject:
    frames = [
        Frame(
            index=i,
            time=float(i) * 2.0,
            atoms=AtomsBlock(
                symbols=["O", "H"],
                positions=np.array([[float(i), 0.0, 0.0], [float(i), 1.0, 0.0]]),
            ),
        )
        for i in range(n_frames)
    ]
    custom: dict[str, Any] = {}
    if with_per_frame:
        custom = {"energy_like": np.arange(n_frames, dtype=float) * 10.0}
    return CanonicalObject(
        frames=frames,
        trajectory=TrajectoryMetadata(timestep=2.0),
        provenance=Provenance(
            source_filename="t.xyz", source_format="xyz", original_coordinate_system="cartesian"
        ),
        user_metadata=UserMetadata(custom_per_frame=custom),
    )


def _run(obj: CanonicalObject, **params: Any) -> Any:
    return apply_repairs(obj, [RepairRequest(operation="select_frames", parameters=params)])


def test_registered_and_selective_reductive() -> None:
    op = get_operation("select_frames")
    assert isinstance(op, SelectFrames)
    assert op.hazard_class == SELECTIVE_REDUCTIVE_HAZARD


def test_slice_semantics_start_stop_step() -> None:
    outcome = _run(_trajectory(10), start=0, stop=10, step=3)
    assert outcome.canonical is not None
    kept = outcome.canonical.frames
    assert [f.time for f in kept] == [0.0, 6.0, 12.0, 18.0]  # source frames 0,3,6,9, time verbatim
    assert [f.index for f in kept] == [0, 1, 2, 3]  # renumbered to their position
    assert [float(f.atoms.positions[0, 0]) for f in kept] == [0.0, 3.0, 6.0, 9.0]


def test_negative_indices_and_open_ends() -> None:
    outcome = _run(_trajectory(10), start=-3)
    assert outcome.canonical is not None
    assert [f.time for f in outcome.canonical.frames] == [14.0, 16.0, 18.0]
    outcome = _run(_trajectory(10), stop=2)
    assert outcome.canonical is not None and outcome.canonical.frame_count == 2


def test_custom_per_frame_is_sliced_with_the_same_indices() -> None:
    outcome = _run(_trajectory(10), start=0, stop=10, step=5)
    assert outcome.canonical is not None
    per_frame = outcome.canonical.user_metadata.custom_per_frame["energy_like"]
    assert list(np.asarray(per_frame)) == [0.0, 50.0]


def test_trajectory_kept_for_many_dropped_for_one() -> None:
    many = _run(_trajectory(10), start=0, stop=4)
    one = _run(_trajectory(10), start=2, stop=3)
    assert many.canonical is not None and many.canonical.trajectory is not None
    assert one.canonical is not None and one.canonical.trajectory is None
    assert one.canonical.frame_count == 1


def test_input_object_is_not_mutated() -> None:
    obj = _trajectory(6)
    _run(obj, start=0, stop=6, step=2)
    assert obj.frame_count == 6 and obj.frames[3].index == 3


def test_record_description_and_hazard() -> None:
    outcome = _run(_trajectory(1000, with_per_frame=False), start=0, stop=100, step=5)
    (applied,) = outcome.applied
    assert applied.description == "Kept frames 0:100:5 (20 of 1000); dropped 980 frames."
    assert applied.parameters["kept_count"] == 20
    assert applied.parameters["dropped_count"] == 980
    assert applied.parameters["total_frames"] == 1000
    (hazard,) = applied.hazards
    assert hazard.code == "SELECT_FRAMES_DROPPED_FRAMES"
    assert "980" in hazard.message


def test_step_greater_than_one_states_the_stale_timestep_in_the_hazard() -> None:
    outcome = _run(_trajectory(10), start=0, stop=10, step=2)
    (applied,) = outcome.applied
    (hazard,) = applied.hazards
    assert "trajectory.timestep (2.0 fs)" in hazard.message
    assert "2 source frames apart" in hazard.message
    contiguous = _run(_trajectory(10), start=0, stop=4)
    (applied,) = contiguous.applied
    assert "timestep" not in applied.hazards[0].message  # step 1: spacing unchanged, no claim


def test_keeping_everything_is_a_recorded_noop_with_no_hazard() -> None:
    outcome = _run(_trajectory(4))
    (applied,) = outcome.applied
    assert applied.hazards == []
    assert "nothing dropped" in applied.description.lower()
    assert outcome.canonical is not None and outcome.canonical.frame_count == 4


def test_empty_selection_blocks_and_applies_nothing() -> None:
    outcome = _run(_trajectory(5), start=7, stop=9)
    assert outcome.canonical is None
    (block,) = outcome.blocked
    assert block.operation == "select_frames"
    assert block.reason == REPAIR_BLOCK_EMPTY_SELECTION
    assert "selects no frames" in block.detail


@pytest.mark.parametrize(
    "params",
    [
        {"step": 0},
        {"step": -1},
        {"step": 1.5},
        {"start": "a"},
        {"stop": 2.5},
        {"unknown": 1},
        {"start": True},
    ],
)
def test_malformed_parameters_raise_repair_error(params: dict[str, Any]) -> None:
    with pytest.raises(RepairError):
        _run(_trajectory(5), **params)


def test_replay_from_recorded_parameters_is_identical() -> None:
    obj = _trajectory(10)
    first = _run(obj, start=1, stop=9, step=2)
    (applied,) = first.applied
    replay = apply_repairs(
        obj, [RepairRequest(operation="select_frames", parameters=applied.parameters)]
    )
    assert first.canonical is not None and replay.canonical is not None
    assert [f.time for f in replay.canonical.frames] == [f.time for f in first.canonical.frames]
