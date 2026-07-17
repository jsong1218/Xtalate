"""extXYZ streaming parse/export equal the whole-file path, and honor the error contract mid-stream
(M12; MASTER_SPEC Part 3 §5). The load-bearing guarantee: chunking changes memory, never bytes."""

from __future__ import annotations

import io
from typing import Any

import pytest

from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.sdk import ParseError
from xtalate.sdk.streaming import export_stream, materialize

_FRAME = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3:forces:R:3 energy={e} config_type=md pbc="T T T"\n'
    "O 0.0 0.0 0.0 0.1 0.0 0.0\n"
    "H 1.0 0.0 0.0 0.0 0.2 0.0\n"
    "H 0.0 1.0 0.0 0.0 0.0 0.3\n"
)


def _traj(n: int) -> bytes:
    return "".join(_FRAME.format(e=f"-1.{i}") for i in range(n)).encode()


def _strip_ts(obj: Any) -> dict[str, Any]:
    d: dict[str, Any] = obj.model_dump(mode="json")
    for h in d["provenance"]["history"]:
        h["timestamp"] = "X"
    return d


@pytest.mark.parametrize("n", [1, 2, 5])
def test_streaming_parse_materializes_to_whole_file_parse(n: int) -> None:
    data = _traj(n)
    parser = ExtxyzParser()
    whole = parser.parse(io.BytesIO(data), filename="t.xyz").canonical
    streamed, issues = materialize(parser.parse_stream(io.BytesIO(data), filename="t.xyz"))
    assert _strip_ts(streamed) == _strip_ts(whole)
    assert issues == []


@pytest.mark.parametrize("n", [1, 2, 5])
def test_streaming_export_is_byte_identical(n: int) -> None:
    data = _traj(n)
    parser, exporter = ExtxyzParser(), ExtxyzExporter()
    whole = parser.parse(io.BytesIO(data), filename="t.xyz").canonical
    b_whole = io.BytesIO()
    exporter.export(whole, b_whole)

    stream = parser.parse_stream(io.BytesIO(data), filename="t.xyz")
    b_stream = io.BytesIO()
    export_stream(exporter, stream.header, stream.frames(), b_stream)
    assert b_stream.getvalue() == b_whole.getvalue()


def test_streaming_parse_empty_file_raises() -> None:
    with pytest.raises(ParseError):
        list(ExtxyzParser().parse_stream(io.BytesIO(b"   \n"), filename="t.xyz").frames())


def test_mid_stream_truncated_frame_raises_at_that_frame() -> None:
    # Two good frames then a third declaring 3 atoms but supplying one line, then EOF.
    data = _traj(2) + b"3\ncomment\nO 0.0 0.0 0.0\n"
    stream = ExtxyzParser().parse_stream(io.BytesIO(data), filename="t.xyz")
    it = stream.frames()
    next(it)
    next(it)  # first two frames stream fine
    with pytest.raises(ParseError) as exc:
        next(it)
    assert any(i.location == "frame 2" for i in exc.value.issues)


def test_mid_stream_variable_atom_count_raises() -> None:
    good = _FRAME.format(e="-1.0")
    variable = "2\nProperties=species:S:1:pos:R:3\nO 0.0 0.0 0.0\nH 1.0 0.0 0.0\n"
    data = (good + variable).encode()
    it = ExtxyzParser().parse_stream(io.BytesIO(data), filename="t.xyz").frames()
    next(it)
    with pytest.raises(ParseError) as exc:
        next(it)
    assert any(i.code == "EXTXYZ_VARIABLE_ATOM_COUNT" for i in exc.value.issues)


def test_non_integer_count_line_raises() -> None:
    with pytest.raises(ParseError) as exc:
        list(ExtxyzParser().parse_stream(io.BytesIO(b"notanumber\nx\n"), filename="t.xyz").frames())
    assert any(i.code == "EXTXYZ_PARSE_ERROR" for i in exc.value.issues)


def test_non_utf8_bytes_raise_encoding_error() -> None:
    with pytest.raises(ParseError) as exc:
        list(ExtxyzParser().parse_stream(io.BytesIO(b"\xff\xfe bad"), filename="t.xyz").frames())
    assert any(i.code == "EXTXYZ_ENCODING_ERROR" for i in exc.value.issues)


def test_streaming_warns_on_varying_per_atom_column() -> None:
    # A per-atom custom column whose values change between frames warns once (whole-file parity).
    f0 = "2\nProperties=species:S:1:pos:R:3:tag:I:1\nO 0.0 0.0 0.0 1\nH 1.0 0.0 0.0 2\n"
    f1 = "2\nProperties=species:S:1:pos:R:3:tag:I:1\nO 0.0 0.0 0.0 9\nH 1.0 0.0 0.0 8\n"
    stream = ExtxyzParser().parse_stream(io.BytesIO((f0 + f1).encode()), filename="t.xyz")
    _, issues = materialize(stream)
    assert any(i.code == "EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE" for i in issues)
