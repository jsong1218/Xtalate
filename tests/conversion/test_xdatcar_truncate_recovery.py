"""``truncate_at_last_valid_frame`` recovery on a streaming source (M13; DECISIONS.md D56).

The half of M12's mid-stream error work that D56 deferred to M13, because extXYZ — M12's only
streaming parser — raises a *non-recoverable* error mid-stream and so had nothing to exercise a
streaming truncate-recovery against. XDATCAR is the format that raises the recoverable hint: an
MD run killed while writing configuration *k* leaves frames 0..k-1 as perfectly good science
behind a corrupt tail.

The rule the whole scenario turns on: keeping that prefix is the **user's** explicit choice,
never the parser's. Without a preset the corrupt file is refused; with one, the kept frames and
the discarded tail are both recorded (P1, P4).
"""

from __future__ import annotations

import pytest

from xtalate.conversion.parse_recovery import ParseRecovery, parse_with_recovery
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

_REGISTRY = default_registry()
_TRUNCATE: dict[str, dict[str, object]] = {"truncate_corrupt_tail": {"choice": "truncate"}}

_HEADER = b"""killed mid-write
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
"""

_GOOD_FRAMES = b"""Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
Direct configuration=     2
  0.25 0.0 0.0
  0.5 0.5 0.5
"""

#: Frame 2's block stops after one of its two atoms — the file ended mid-configuration.
MISSING_ROW = _HEADER + _GOOD_FRAMES + b"Direct configuration=     3\n  0.5 0.0 0.0\n"

#: Frame 2's block has a coordinate line torn mid-write (two components, not three).
SHORT_ROW = _HEADER + _GOOD_FRAMES + b"Direct configuration=     3\n  0.5 0.0\n  0.5 0.5 0.5\n"

#: Frame 2's coordinate line is garbage — a partially flushed write.
GARBLED_ROW = _HEADER + _GOOD_FRAMES + b"Direct configuration=     3\n  0.5 0.0 0.0x\n"

#: The very first configuration is torn: there is no valid prefix to keep.
FIRST_FRAME_TORN = _HEADER + b"Direct configuration=     1\n  0.0 0.0 0.0\n"


def _recover(data: bytes, choices: dict[str, dict[str, object]] | None = None) -> ParseRecovery:
    return parse_with_recovery(
        _REGISTRY, data, filename="XDATCAR", recovery_choices=choices or _TRUNCATE
    )


@pytest.mark.parametrize(
    ("name", "data"),
    [("missing_row", MISSING_ROW), ("short_row", SHORT_ROW), ("garbled_row", GARBLED_ROW)],
)
def test_every_torn_write_shape_is_recoverable(name: str, data: bytes) -> None:
    """A process killed mid-write can leave a missing row, a half-written row, or a garbled one.
    All three are the same event, so all three carry the recoverable hint — treating only the
    missing-row case as recoverable would refuse files that are just as salvageable."""
    result = _recover(data)
    assert result.canonical.frame_count == 2


def test_without_a_preset_the_corrupt_file_is_refused() -> None:
    """Refusal is the default (Part 4 §4). Silently keeping the prefix would be the engine
    deciding, on the user's behalf, that the lost tail did not matter."""
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_REGISTRY, MISSING_ROW, filename="XDATCAR")
    assert exc.value.issues[0].recovery_hint == "truncate_at_last_valid_frame"


def test_abort_is_an_explicit_give_up() -> None:
    with pytest.raises(ParseError):
        _recover(MISSING_ROW, {"truncate_corrupt_tail": {"choice": "abort"}})


def test_the_kept_frames_are_the_genuine_ones() -> None:
    obj = _recover(MISSING_ROW).canonical
    assert [f.index for f in obj.frames] == [0, 1]
    # 0.25 fractional of a 5.6 Å cell = 1.4 Å: the surviving frames are read exactly as they
    # would be from an intact file, not approximated.
    assert obj.frames[1].atoms.positions[0].tolist() == [1.4, 0.0, 0.0]


def test_the_truncation_is_recorded_as_an_assumption() -> None:
    result = _recover(MISSING_ROW)
    assumption = result.assumptions[0]
    assert assumption.scenario == "truncate_corrupt_tail"
    assert assumption.choice == "truncate"
    assert assumption.parameters["kept_frames"] == 2
    assert "discarded the corrupt tail" in assumption.description


def test_the_dropped_tail_is_recorded_as_removed() -> None:
    """Selective-reductive, not fabricative: the frames that survive are genuine source data, so
    the tail is `removed` and nothing is `supplied`."""
    assumption = _recover(MISSING_ROW).assumptions[0]
    assert [d.path for d in assumption.removed] == ["atoms.positions"]
    assert assumption.supplied == []


def test_a_warning_records_the_truncation_on_the_parse_result() -> None:
    result = _recover(MISSING_ROW)
    assert "XDATCAR_TRUNCATED" in {i.code for i in result.issues}


def test_truncating_to_nothing_is_not_a_recovery() -> None:
    """No valid prefix means the honest answer is still the original error. Returning an empty
    frame list instead would trip the schema's own minimum and surface as a raw pydantic
    ValidationError — escaping the Part 3 §5 error contract entirely."""
    with pytest.raises(ParseError) as exc:
        _recover(FIRST_FRAME_TORN)
    assert exc.value.issues[0].code == "XDATCAR_TRUNCATED_CONFIGURATION"


def test_a_structurally_wrong_file_is_not_truncated_away() -> None:
    """The guard that keeps truncate-mode honest: only errors the parser marked *recoverable* end
    the stream. A file whose atom count changes mid-trajectory is not a torn tail — it is wrong —
    so `truncate` must not quietly convert it into a short, plausible-looking trajectory."""
    variable_count = (
        _HEADER
        + _GOOD_FRAMES
        + b"""killed mid-write
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 2
Direct configuration=     3
  0.5 0.0 0.0
  0.5 0.5 0.5
  0.1 0.1 0.1
"""
    )
    with pytest.raises(ParseError) as exc:
        _recover(variable_count)
    assert exc.value.issues[0].code == "XDATCAR_VARIABLE_ATOM_COUNT"


def test_an_intact_file_needs_no_recovery_and_invents_no_truncation() -> None:
    result = _recover(_HEADER + _GOOD_FRAMES)
    assert result.canonical.frame_count == 2
    assert result.assumptions == []
    assert "XDATCAR_TRUNCATED" not in {i.code for i in result.issues}


def test_recovery_keeps_the_prefix_lazily() -> None:
    """The recovery must not give up the streaming property it exists to serve: the good frames
    are yielded one at a time, so a torn 10⁴-frame file recovers with one frame resident."""
    from xtalate.parsers.xdatcar import make_xdatcar_parser

    stream = make_xdatcar_parser().parse_stream(
        __import__("io").BytesIO(MISSING_ROW), filename="XDATCAR", truncate=True
    )
    frames = stream.frames()
    assert next(frames).frame.index == 0
    assert next(frames).frame.index == 1
    with pytest.raises(StopIteration):
        next(frames)
    assert "XDATCAR_TRUNCATED" in {i.code for i in stream.issues}
