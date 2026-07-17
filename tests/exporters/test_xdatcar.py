"""XDATCAR exporter tests (M13): Direct output, the single-pass fixed-cell/NpT header rule,
element grouping and its permutation map, the streaming write path, and the capability
declaration (Part 3 §3, §4.2, Part 4 §1)."""

from __future__ import annotations

import io

import numpy as np
import pytest

from xtalate.exporters.xdatcar import make_xdatcar_exporter
from xtalate.parsers.xdatcar import make_xdatcar_parser
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    Provenance,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.sdk.streaming import stream_of


def _provenance() -> Provenance:
    return Provenance(
        source_filename=None, source_format="test", original_coordinate_system="cartesian"
    )


def _object(
    frames: list[Frame], *, title: str = "test trajectory", trajectory: bool = True
) -> CanonicalObject:
    return CanonicalObject(
        frames=frames,
        trajectory=TrajectoryMetadata(timestep=None) if trajectory else None,
        provenance=_provenance(),
        user_metadata=UserMetadata(custom_global={"xdatcar:comment": title}),
    )


def _frame(index: int, positions: list[list[float]], cell_a: float, symbols: list[str]) -> Frame:
    return Frame(
        index=index,
        atoms=AtomsBlock(symbols=symbols, positions=np.asarray(positions, dtype=float)),
        cell=Cell(lattice_vectors=np.eye(3) * cell_a, pbc=(True, True, True)),
    )


def _export(obj: CanonicalObject) -> str:
    buf = io.BytesIO()
    make_xdatcar_exporter().export(obj, buf)
    return buf.getvalue().decode("utf-8")


def _reparse(obj: CanonicalObject) -> CanonicalObject:
    buf = io.BytesIO()
    make_xdatcar_exporter().export(obj, buf)
    return make_xdatcar_parser().parse(io.BytesIO(buf.getvalue()), filename="XDATCAR").canonical


FIXED = [
    _frame(0, [[0.0, 0.0, 0.0], [2.8, 2.8, 2.8]], 5.6, ["Na", "Cl"]),
    _frame(1, [[0.56, 0.0, 0.0], [2.8, 2.8, 2.8]], 5.6, ["Na", "Cl"]),
]

NPT = [
    _frame(0, [[0.0, 0.0, 0.0], [2.8, 2.8, 2.8]], 5.6, ["Na", "Cl"]),
    _frame(1, [[0.0, 0.0, 0.0], [2.9, 2.9, 2.9]], 5.8, ["Na", "Cl"]),
]


# --- Direct output ------------------------------------------------------------------------


def test_positions_are_written_in_vasps_direct_convention() -> None:
    text = _export(_object(FIXED))
    assert "Direct configuration=" in text
    lines = text.splitlines()
    coords = lines[lines.index("Direct configuration=      1") + 1 :][:2]
    # 2.8 Å in a 5.6 Å cubic cell is fractional 0.5 — written Direct, not Cartesian.
    assert [float(t) for t in coords[1].split()] == pytest.approx([0.5, 0.5, 0.5])


def test_configurations_are_numbered_from_one() -> None:
    text = _export(_object(FIXED))
    assert "Direct configuration=      1" in text
    assert "Direct configuration=      2" in text


def test_cartesian_positions_survive_the_direct_round_trip() -> None:
    obj = _object(FIXED)
    back = _reparse(obj)
    for before, after in zip(obj.frames, back.frames, strict=True):
        np.testing.assert_allclose(before.atoms.positions, after.atoms.positions, atol=1e-12)


# --- the single-pass fixed-cell / NpT header rule -----------------------------------------


def test_fixed_cell_trajectory_writes_one_header() -> None:
    """A cell that never moves gets VASP's compact form: the header appears once."""
    text = _export(_object(FIXED))
    assert text.count("Na Cl") == 1


def test_npt_trajectory_restates_the_header_per_moved_cell() -> None:
    """A cell that moves gets VASP's NpT form. Collapsing an NpT run onto frame 0's lattice
    would be silent loss (P1) — the restated header is what preserves it."""
    text = _export(_object(NPT))
    assert text.count("Na Cl") == 2


def test_npt_per_frame_cells_survive_the_round_trip() -> None:
    back = _reparse(_object(NPT))
    assert back.frames[0].cell is not None
    assert back.frames[1].cell is not None
    np.testing.assert_allclose(back.frames[0].cell.lattice_vectors, np.eye(3) * 5.6)
    np.testing.assert_allclose(back.frames[1].cell.lattice_vectors, np.eye(3) * 5.8)


def test_header_is_restated_only_when_the_cell_actually_moves() -> None:
    """The rule compares against the *previous* frame, which is what keeps it single-pass. A
    trajectory that returns to an earlier cell restates only at each change."""
    frames = [
        _frame(0, [[0.0, 0.0, 0.0]], 5.6, ["Si"]),
        _frame(1, [[0.0, 0.0, 0.0]], 5.6, ["Si"]),
        _frame(2, [[0.0, 0.0, 0.0]], 5.8, ["Si"]),
    ]
    text = _export(_object(frames))
    assert text.count("\nSi\n") == 2  # once up front, once when the cell moved at frame 2


# --- element grouping ---------------------------------------------------------------------


def test_atoms_are_grouped_by_element_and_the_permutation_is_reported() -> None:
    """XDATCAR declares species + counts, so one element's atoms must be contiguous. The
    reorder is reported to the Validation Engine rather than left for it to guess (Part 5 §2)."""
    frames = [
        _frame(
            0,
            [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
            5.0,
            ["Na", "Cl", "Na"],
        )
    ]
    obj = _object(frames, trajectory=False)
    text = _export(obj)
    assert "Na Cl" in text
    assert "2 1" in text
    assert make_xdatcar_exporter().atom_permutation(obj) == [0, 2, 1]
    back = _reparse(obj)
    assert back.frames[0].atoms.symbols == ["Na", "Na", "Cl"]


def test_already_grouped_atoms_report_no_permutation() -> None:
    assert make_xdatcar_exporter().atom_permutation(_object(FIXED)) is None


# --- title --------------------------------------------------------------------------------


def test_title_is_written_and_survives_the_round_trip() -> None:
    obj = _object(FIXED, title="my md run")
    assert _export(obj).startswith("my md run\n")
    assert _reparse(obj).user_metadata.custom_global["xdatcar:comment"] == "my md run"


def test_object_without_a_title_writes_an_empty_title_line() -> None:
    obj = CanonicalObject(frames=FIXED, provenance=_provenance())
    assert _export(obj).startswith("\n1.0\n")


# --- refusals -----------------------------------------------------------------------------


def test_frame_without_a_cell_is_refused_not_fabricated() -> None:
    frame = Frame(
        index=0,
        atoms=AtomsBlock(symbols=["Si"], positions=np.zeros((1, 3))),
        cell=None,
    )
    with pytest.raises(ValueError, match="missing_lattice"):
        _export(_object([frame], trajectory=False))


def test_empty_frame_stream_is_refused_rather_than_writing_an_empty_file() -> None:
    """``CanonicalObject`` already forbids an empty ``frames`` list, so this is unreachable via
    ``export``; ``export_stream`` takes a bare iterator, so the contract check belongs there —
    an empty stream must fail loudly, not produce a headerless file that parses as nothing."""
    header = stream_of(_object(FIXED)).header
    with pytest.raises(ValueError, match="at least one configuration"):
        make_xdatcar_exporter().export_stream(header, iter([]), io.BytesIO())


# --- streaming (M12 surface) --------------------------------------------------------------


def test_exporter_declares_streaming_support() -> None:
    assert make_xdatcar_exporter().supports_streaming() is True


def test_streamed_and_whole_file_writings_are_byte_identical() -> None:
    """``export`` *is* ``export_stream`` over the object's frames, so this pins the property
    that makes that definition safe (D56)."""
    obj = _object(NPT)
    whole = io.BytesIO()
    make_xdatcar_exporter().export(obj, whole)
    streamed = io.BytesIO()
    fs = stream_of(obj)
    make_xdatcar_exporter().export_stream(fs.header, fs.frames(), streamed)
    assert whole.getvalue() == streamed.getvalue()


# --- capabilities (Part 3 §4.2) -----------------------------------------------------------


def test_capabilities_declare_an_unbounded_frame_count() -> None:
    """The whole point of the format — and what makes it the honest test of M12's chunking."""
    assert make_xdatcar_exporter().capabilities().max_frames is None


def test_capabilities_declare_no_velocity_block() -> None:
    """XDATCAR is positions-over-time and nothing else; velocities are CONTCAR's. Declaring
    this is what makes the pre-flight report a dropped velocity rather than the exporter
    silently omitting it (P5)."""
    caps = make_xdatcar_exporter().capabilities()
    assert caps.fields["dynamics.velocities"].level == "none"


def test_capabilities_restrict_writable_custom_global_keys_to_the_title() -> None:
    caps = make_xdatcar_exporter().capabilities()
    assert caps.writable_custom_keys["user_metadata.custom_global"] == ["xdatcar:comment"]
