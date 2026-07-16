"""SDK streaming surface: header/frame split, materialize/stream_of round-trips, single-pass
enforcement, and the whole-file → streaming adapters (M12)."""

from __future__ import annotations

import io

import numpy as np
import pytest

from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Frame,
    Provenance,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.sdk import ParseIssue
from xtalate.sdk.streaming import (
    FrameStream,
    StreamFrame,
    StreamHeader,
    export_stream,
    materialize,
    parse_as_stream,
    stream_of,
)


def _obj(n_frames: int = 3, *, with_cell_frame0: bool = True) -> CanonicalObject:
    frames = []
    for i in range(n_frames):
        cell = (
            Cell(lattice_vectors=np.eye(3) * 5.0, pbc=(True, True, True))
            if (with_cell_frame0 and i == 0)
            else None
        )
        frames.append(
            Frame(
                index=i,
                atoms=AtomsBlock(symbols=["O", "H"], positions=np.array([[0.0, 0, 0], [1, 0, 0]])),
                cell=cell,
                dynamics=Dynamics(velocities=np.zeros((2, 3)) if i == 1 else None),
            )
        )
    return CanonicalObject(
        frames=frames,
        trajectory=TrajectoryMetadata(timestep=None) if n_frames > 1 else None,
        simulation=SimulationMetadata(source_code="vasp"),
        provenance=Provenance(
            source_filename="t.xyz", source_format="extxyz", original_coordinate_system="cartesian"
        ),
        user_metadata=UserMetadata(
            tags=["a"],
            custom_global={"g": 1},
            custom_per_atom={"lab": ["x", "y"]},
            custom_per_frame={"c": [10, None, 30]} if n_frames == 3 else {},
        ),
    )


def test_stream_of_then_materialize_is_identity() -> None:
    obj = _obj()
    back, issues = materialize(stream_of(obj))
    assert back.model_dump(mode="json") == obj.model_dump(mode="json")
    assert issues == []


def test_stream_of_carries_issues_through_materialize() -> None:
    obj = _obj()
    warn = ParseIssue(severity="warning", code="X", message="m")
    _, issues = materialize(stream_of(obj, issues=[warn]))
    assert [i.code for i in issues] == ["X"]


def test_header_from_object_splits_frame_independent_metadata() -> None:
    obj = _obj()
    header = StreamHeader.from_object(obj)
    assert header.tags == ["a"]
    assert header.custom_global == {"g": 1}
    assert header.custom_per_atom == {"lab": ["x", "y"]}
    assert header.simulation is not None and header.simulation.source_code == "vasp"


def test_single_frame_stream_materializes_without_trajectory() -> None:
    obj = _obj(n_frames=1)
    back, _ = materialize(stream_of(obj))
    assert back.trajectory is None
    assert back.frame_count == 1


def test_frames_is_single_pass() -> None:
    stream = stream_of(_obj())
    list(stream.frames())
    with pytest.raises(RuntimeError, match="single-pass"):
        list(stream.frames())


def test_frame_stream_default_issues_list_is_independent() -> None:
    a = FrameStream(StreamHeader("0.1.0", _obj().provenance), iter(()))
    b = FrameStream(StreamHeader("0.1.0", _obj().provenance), iter(()))
    a.issues.append(ParseIssue(severity="warning", code="A", message="m"))
    assert b.issues == []


def test_parse_as_stream_uses_whole_file_parser_when_not_streaming() -> None:
    # POSCAR does not implement parse_stream; parse_as_stream adapts it via stream_of.
    from xtalate.parsers.poscar import PoscarParser

    poscar = b"test\n1.0\n5.0 0 0\n0 5.0 0\n0 0 5.0\nH\n1\nCartesian\n0.0 0.0 0.0\n"
    parser = PoscarParser()
    assert parser.supports_streaming() is False
    stream = parse_as_stream(parser, poscar, filename="POSCAR")
    obj, _ = materialize(stream)
    assert obj.frames[0].atoms.symbols == ["H"]


def test_export_stream_materializes_for_non_streaming_exporter() -> None:
    # Plain XYZ exporter does not implement export_stream; export_stream materializes for it.
    from xtalate.exporters.xyz import XyzExporter

    exporter = XyzExporter()
    assert exporter.supports_streaming() is False
    obj = _obj(n_frames=2, with_cell_frame0=False)
    header = StreamHeader.from_object(obj)
    frames = (StreamFrame(frame=f) for f in obj.frames)
    out = io.BytesIO()
    export_stream(exporter, header, frames, out)
    assert b"O" in out.getvalue() and b"H" in out.getvalue()
