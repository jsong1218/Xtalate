"""Streaming ``frame_selection`` into a single-structure target (M13; DECISIONS.md D56).

The recovery interplay M12 deferred: a multi-frame streaming source (XDATCAR) into a target that
holds one structure (POSCAR). ``convert_stream_select`` reduces the trajectory to the chosen frame
in a single pass — one frame resident — and its Conversion Report and output bytes are
**byte-identical** to the materialized ``convert(source, recovery_choices={"frame_selection": …})``
on the same file (standing rule 3: chunking changes memory, never report truth).

The genuine test is the equality itself: whatever subtle accounting the materialized recovery does
(dropped-frame ``removed`` entry, the assumption's description and parameters, the capability diff
for a POSCAR that cannot store the trajectory axis) the streamed path must reproduce exactly, not
approximate.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from xtalate.conversion.engine import ConversionEngine
from xtalate.parsers.xdatcar import make_xdatcar_parser
from xtalate.recovery import RecoveryError
from xtalate.registry import default_registry

_HEADER = """cubic cell
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
"""


def _traj(n: int) -> bytes:
    """An ``n``-configuration fixed-cell XDATCAR whose atoms drift per frame, so every frame is
    distinguishable and ``first``/``last``/``index`` genuinely differ."""
    blocks = []
    for i in range(n):
        a = 0.01 * i
        blocks.append(f"Direct configuration=  {i + 1:>5}\n  {a:.6f} 0.0 0.0\n  0.5 0.5 0.5\n")
    return (_HEADER + "".join(blocks)).encode()


def _norm(report: Any) -> dict[str, object]:
    d: dict[str, object] = report.model_dump(mode="json")
    d["report_id"] = "X"
    d["created_at"] = "X"
    # Provenance conversion-history timestamps are wall-clock; the report embeds none, but the
    # assumptions/paths that matter for standing rule 3 are all deterministic and compared as-is.
    return d


@pytest.fixture
def engine() -> ConversionEngine:
    return ConversionEngine(default_registry())


def _materialized(engine: ConversionEngine, data: bytes, choice: dict[str, Any], **kw: Any) -> Any:
    src = make_xdatcar_parser().parse(io.BytesIO(data), filename="XDATCAR").canonical
    return engine.convert(
        src,
        source_format_id="xdatcar",
        target_format_id="poscar",
        source_filename="XDATCAR",
        recovery_choices={"frame_selection": choice},
        **kw,
    )


def _streamed(engine: ConversionEngine, data: bytes, choice: dict[str, Any], **kw: Any) -> Any:
    out = io.BytesIO()
    return (
        engine.convert_stream_select(
            io.BytesIO(data),
            source_format_id="xdatcar",
            target_format_id="poscar",
            output=out,
            frame_selection=choice,
            source_filename="XDATCAR",
            **kw,
        ),
        out,
    )


@pytest.mark.parametrize("n", [2, 3, 10])
@pytest.mark.parametrize(
    "choice",
    [
        {"choice": "first"},
        {"choice": "last"},
        {"choice": "index", "parameters": {"frame_index": 1}},
    ],
)
def test_streamed_report_and_output_equal_materialized(
    engine: ConversionEngine, n: int, choice: dict[str, Any]
) -> None:
    data = _traj(n)
    materialized = _materialized(engine, data, choice)
    streamed, out = _streamed(engine, data, choice)

    assert _norm(streamed.report) == _norm(materialized.report)
    assert out.getvalue() == materialized.output
    assert streamed.validation is not None and materialized.validation is not None
    assert streamed.validation.status == materialized.validation.status


def test_the_retained_frame_is_the_chosen_one(engine: ConversionEngine) -> None:
    # `last` of a 10-frame run drifts the first atom to x = 0.09 · 5.6 Å = 0.504 Å; `first` keeps
    # it at the origin. The streamed reduction keeps the genuine frame, not an approximation.
    streamed_last, _ = _streamed(engine, _traj(10), {"choice": "last"})
    streamed_first, _ = _streamed(engine, _traj(10), {"choice": "first"})
    assert streamed_last.canonical_out.frames[0].atoms.positions[0][0] == pytest.approx(0.504)
    assert streamed_first.canonical_out.frames[0].atoms.positions[0][0] == pytest.approx(0.0)


def test_the_dropped_frames_are_recorded_removed(engine: ConversionEngine) -> None:
    streamed, _ = _streamed(engine, _traj(4), {"choice": "first"})
    removed_paths = {e.path for e in streamed.report.removed}
    assert "atoms.positions" in removed_paths  # the 3 dropped frames
    assumption = streamed.report.assumptions[0]
    assert assumption.scenario == "frame_selection"
    assert assumption.parameters["frame_index"] == 0


def test_strict_mode_refuses_unacknowledged_loss(engine: ConversionEngine) -> None:
    streamed, out = _streamed(engine, _traj(3), {"choice": "first"}, mode="strict")
    assert streamed.report.status == "refused"
    assert streamed.report.refusal is not None
    assert streamed.report.refusal["code"] == "UNACKNOWLEDGED_LOSS"
    assert streamed.validation is None
    assert out.getvalue() == b""  # nothing written on a refusal


def test_strict_mode_acknowledged_matches_materialized(engine: ConversionEngine) -> None:
    data = _traj(3)
    choice = {"choice": "last"}
    materialized = _materialized(engine, data, choice, mode="strict", acknowledge_loss=True)
    streamed, out = _streamed(engine, data, choice, mode="strict", acknowledge_loss=True)
    assert _norm(streamed.report) == _norm(materialized.report)
    assert out.getvalue() == materialized.output


def test_eligibility_gate(engine: ConversionEngine) -> None:
    # XDATCAR→POSCAR is the streaming frame-selection case; the trajectory pass-through and the
    # non-streaming source are not.
    assert engine.frame_selection_streaming_eligible("xdatcar", "poscar") is True
    assert engine.frame_selection_streaming_eligible("xdatcar", "extxyz") is False  # not capped
    assert (
        engine.frame_selection_streaming_eligible("xyz", "poscar") is False
    )  # xyz isn't streaming


def test_ineligible_pair_is_refused_to_convert(engine: ConversionEngine) -> None:
    with pytest.raises(ValueError, match="frame-selection-streaming-eligible"):
        engine.convert_stream_select(
            io.BytesIO(_traj(2)),
            source_format_id="xdatcar",
            target_format_id="extxyz",
            output=io.BytesIO(),
            frame_selection={"choice": "first"},
        )


def test_split_all_is_refused_to_convert(engine: ConversionEngine) -> None:
    with pytest.raises(ValueError, match="split_all"):
        engine.convert_stream_select(
            io.BytesIO(_traj(2)),
            source_format_id="xdatcar",
            target_format_id="poscar",
            output=io.BytesIO(),
            frame_selection={"choice": "split_all"},
        )


def test_out_of_range_index_raises(engine: ConversionEngine) -> None:
    with pytest.raises(RecoveryError):
        _streamed(engine, _traj(3), {"choice": "index", "parameters": {"frame_index": 9}})


def test_memory_bounded_capture_holds_one_frame(engine: ConversionEngine) -> None:
    """A ``last`` selection over a long trajectory must not accumulate frames: the pass captures the
    running-last plus frame 0, never a growing list. Proven structurally — the reduced object is a
    single frame regardless of source length."""
    streamed, _ = _streamed(engine, _traj(50), {"choice": "last"})
    assert streamed.canonical_out.frame_count == 1


# --- CIF as the single-structure target (v0.4 review, tier 5.2) --------------------------------
#
# `frame_selection_streaming_eligible` gates on "the source streams" plus `max_frames == 1` on the
# target, so CIF became a live streaming target the moment it registered — with no test naming it.
# The route is real: xdatcar → cif reports eligible today. It is the same code path POSCAR
# exercises above, which is exactly the argument for pinning it rather than assuming it: the
# streamed path hands the retained frame to the exporter's ordinary whole-file `export`, and CIF is
# the only target whose `export` refuses a multi-frame object outright, so a reduction that
# silently failed to reduce would surface here as a refusal rather than a wrong file.


def _streamed_to(engine: ConversionEngine, data: bytes, target: str, choice: dict[str, Any]) -> Any:
    out = io.BytesIO()
    result = engine.convert_stream_select(
        io.BytesIO(data),
        source_format_id="xdatcar",
        target_format_id=target,
        output=out,
        frame_selection=choice,
        source_filename="XDATCAR",
    )
    return result, out


def test_a_trajectory_streams_into_cif_the_same_as_it_materializes() -> None:
    # Standing rule 3 for the pair v0.4 added: chunking changes memory, never report truth.
    engine = ConversionEngine(default_registry())
    data = _traj(10)
    choice = {"choice": "last"}
    source = make_xdatcar_parser().parse(io.BytesIO(data), filename="XDATCAR").canonical
    materialized = engine.convert(
        source,
        source_format_id="xdatcar",
        target_format_id="cif",
        source_filename="XDATCAR",
        recovery_choices={"frame_selection": choice},
    )
    streamed, out = _streamed_to(engine, data, "cif", choice)

    assert _norm(streamed.report) == _norm(materialized.report)
    assert out.getvalue() == materialized.output
    assert b"data_" in out.getvalue()  # a real CIF, not an empty artifact


def test_the_frame_cif_receives_is_the_chosen_one() -> None:
    # The reduction has to happen *before* the exporter, and be the right frame. `last` of the
    # 10-frame run drifts the first atom to 0.09 fractional; `first` leaves it at the origin.
    engine = ConversionEngine(default_registry())
    last, _ = _streamed_to(engine, _traj(10), "cif", {"choice": "last"})
    first, _ = _streamed_to(engine, _traj(10), "cif", {"choice": "first"})
    assert last.canonical_out.frames[0].atoms.positions[0][0] == pytest.approx(0.504)
    assert first.canonical_out.frames[0].atoms.positions[0][0] == pytest.approx(0.0)


def test_cif_as_a_source_is_not_offered_the_streaming_route() -> None:
    # The other half of the gate, asserted so a future `parse_stream` on the CIF parser cannot
    # quietly enrol a single-structure format in a frame-selection path that means nothing for it.
    engine = ConversionEngine(default_registry())
    assert engine.frame_selection_streaming_eligible("cif", "poscar") is False
    assert engine.streaming_eligible("cif", "cif") is False
    # ...while a genuine trajectory source into CIF is eligible, so the assertion above is about
    # CIF-as-source specifically and not about CIF being excluded everywhere.
    assert engine.frame_selection_streaming_eligible("xdatcar", "cif") is True
