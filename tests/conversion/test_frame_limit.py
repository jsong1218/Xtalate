"""The frame cap made real (M39-S3, the M37 finding-F1 / D128 ticket): ``FrameLimitExceeded`` fires
mid-stream, never after materializing.

The advertised ``max_frames`` gate (Part 6 §5) was an advisory hint through the v1.0 freeze;
M39-S3 enforces it. These tests pin the library-side contract: the entry points that read frames
under a cap — ``convert_stream``, ``parse_with_recovery``, and ``DiscoveryEngine.discover`` — count
**as they stream** and raise ``FrameLimitExceeded`` carrying the count-so-far and the cap, *before*
the remaining frames are read. The over-cap proof is the corrupt-tail variant: a file whose third
frame cannot be parsed, read under a cap of 1, must fail with the cap refusal (frame 2) — never the
parse error of a frame the cap says should never be read.
"""

from __future__ import annotations

import io

import pytest

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, FrameLimitExceeded, parse_with_recovery
from xtalate.discovery import DiscoveryEngine
from xtalate.registry import default_registry

# One extXYZ frame, 3 atoms, with an energy slot so successive frames are distinguishable.
_FRAME = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3:forces:R:3 energy={e} config_type=md pbc="T T T"\n'
    "O 0.0 0.0 0.0 0.1 0.0 0.0\n"
    "H 1.0 0.0 0.0 0.0 0.2 0.0\n"
    "H 0.0 1.0 0.0 0.0 0.0 0.3\n"
)

# The same frame with one atom line dropped — parsing it raises ``ParseError`` (inconsistent atom
# count), so it can prove a reader stopped before reaching it.
_FRAME_CORRUPT = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3:forces:R:3 energy={e} config_type=md pbc="T T T"\n'
    "O 0.0 0.0 0.0 0.1 0.0 0.0\n"
    "H 1.0 0.0 0.0 0.0 0.2 0.0\n"
)


def _traj(n: int, *, corrupt_last: bool = False) -> bytes:
    """``n`` good frames, optionally with the final frame corrupt (one atom line dropped)."""
    frames = [_FRAME.format(e=f"-1.{i}") for i in range(n)]
    if corrupt_last:
        frames[-1] = _FRAME_CORRUPT.format(e=f"-1.{n}")
    return "".join(frames).encode()


POSCAR = b"""single structure
1.0
  4.0 0.0 0.0
  0.0 4.0 0.0
  0.0 0.0 4.0
Si
2
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
"""


@pytest.fixture
def engine() -> ConversionEngine:
    return ConversionEngine(default_registry())


@pytest.fixture
def registry() -> Registry:
    return default_registry()


# --- convert_stream: counted as it streams -------------------------------------------------------


def test_convert_stream_raises_mid_stream_at_the_cap(engine: ConversionEngine) -> None:
    out = io.BytesIO()
    with pytest.raises(FrameLimitExceeded) as excinfo:
        engine.convert_stream(
            io.BytesIO(_traj(3)),
            source_format_id="extxyz",
            target_format_id="extxyz",
            output=out,
            max_frames=2,
        )
    assert excinfo.value.frame_count == 3  # the count-so-far when the gate fired
    assert excinfo.value.max_frames == 2
    # The partial write is discarded — no half-written output can masquerade as a conversion.
    assert out.getvalue() == b""


def test_convert_stream_stops_before_the_cap_and_never_reads_the_corrupt_frame(
    engine: ConversionEngine,
) -> None:
    # Frame 3 is corrupt (unparseable). Under a cap of 1 the refusal must fire at frame 2 — the
    # corrupt frame is *never* read, proving the check happens mid-stream, not after materializing.
    with pytest.raises(FrameLimitExceeded) as excinfo:
        engine.convert_stream(
            io.BytesIO(_traj(3, corrupt_last=True)),
            source_format_id="extxyz",
            target_format_id="extxyz",
            output=io.BytesIO(),
            max_frames=1,
        )
    assert excinfo.value.frame_count == 2


def test_convert_stream_at_cap_succeeds(engine: ConversionEngine) -> None:
    out = io.BytesIO()
    result = engine.convert_stream(
        io.BytesIO(_traj(3)),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=out,
        max_frames=3,
    )
    assert result.report.status == "completed"
    assert out.getvalue()  # the conversion ran to completion


# --- parse_with_recovery: the materialized seam refuses before materializing ---------------------


def test_parse_with_recovery_raises_before_the_materialized_parse(registry: Registry) -> None:
    with pytest.raises(FrameLimitExceeded) as excinfo:
        parse_with_recovery(registry, _traj(3), filename="t.xyz", max_frames=2)
    assert excinfo.value.frame_count == 3


def test_parse_with_recovery_never_reads_past_the_cap(registry: Registry) -> None:
    # The corrupt third frame would raise ParseError without a cap; with a cap of 1 the count pass
    # halts at frame 2 and the cap refusal wins — the materialized parse (and its recovery path)
    # never runs.
    with pytest.raises(FrameLimitExceeded) as excinfo:
        parse_with_recovery(registry, _traj(3, corrupt_last=True), filename="t.xyz", max_frames=1)
    assert excinfo.value.frame_count == 2


def test_parse_with_recovery_at_cap_succeeds(registry: Registry) -> None:
    parsed = parse_with_recovery(registry, _traj(3), filename="t.xyz", max_frames=3)
    assert parsed.canonical.frame_count == 3


def test_single_structure_formats_skip_the_count_pass(registry: Registry) -> None:
    # POSCAR declares a read max_frames of 1, which can never exceed the cap — the count pass is
    # skipped and the parse runs once (the skip exists so single-structure jobs pay nothing).
    parsed = parse_with_recovery(registry, POSCAR, filename="cell.poscar", max_frames=1)
    assert parsed.canonical.frame_count == 1


# --- discover: an inspect job is covered too -----------------------------------------------------


def test_discover_raises_for_an_over_cap_trajectory() -> None:
    with pytest.raises(FrameLimitExceeded) as excinfo:
        DiscoveryEngine(default_registry()).discover(_traj(3), filename="t.xyz", max_frames=2)
    assert excinfo.value.frame_count == 3


def test_discover_at_cap_succeeds() -> None:
    report = DiscoveryEngine(default_registry()).discover(_traj(3), filename="t.xyz", max_frames=3)
    assert report.structure["frame_count"] == 3


def test_no_cap_keeps_the_current_behaviour(registry: Registry) -> None:
    # Default None = no gate: the corrupt-tail file surfaces its parse error, exactly as before.
    from xtalate.sdk import ParseError

    with pytest.raises(ParseError):
        parse_with_recovery(registry, _traj(3, corrupt_last=True), filename="t.xyz")
