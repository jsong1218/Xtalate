"""The streaming Conversion path (``convert_stream``) produces the *identical* Conversion Report as
the materialized ``convert``, and streams byte-identical output — the standing-rule-3 guarantee that
chunking changes memory, never report truth (M12, deliverable 3)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any, BinaryIO

import pytest

from xtalate.capabilities import Registry
from xtalate.conversion.engine import ConversionEngine
from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.registry import default_registry
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    StreamFrame,
    StreamHeader,
    export_stream,
)

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


def _norm(report: Any) -> dict[str, object]:
    d: dict[str, object] = report.model_dump(mode="json")
    d["report_id"] = "X"
    d["created_at"] = "X"
    return d


@pytest.fixture
def engine() -> ConversionEngine:
    return ConversionEngine(default_registry())


@pytest.mark.parametrize("n", [1, 3, 6])
def test_streamed_report_equals_materialized(engine: ConversionEngine, n: int) -> None:
    data = _traj(n)
    src = ExtxyzParser().parse(io.BytesIO(data), filename="t.xyz").canonical
    materialized = engine.convert(
        src, source_format_id="extxyz", target_format_id="extxyz", source_filename="t.xyz"
    )
    out = io.BytesIO()
    streamed = engine.convert_stream(
        io.BytesIO(data),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=out,
        source_filename="t.xyz",
    )
    assert _norm(streamed.report) == _norm(materialized.report)
    assert out.getvalue() == materialized.output
    assert streamed.validation is not None
    assert materialized.validation is not None
    assert streamed.validation.status == materialized.validation.status


def test_streaming_eligibility_gate(engine: ConversionEngine) -> None:
    # extXYZ→extXYZ streams (pass-through). extXYZ→POSCAR does not (POSCAR requires a lattice and
    # caps frames — it can need recovery), and neither does a non-streaming source.
    assert engine.streaming_eligible("extxyz", "extxyz") is True
    assert engine.streaming_eligible("extxyz", "poscar") is False
    assert engine.streaming_eligible("poscar", "extxyz") is False


def test_convert_stream_refuses_ineligible_pair(engine: ConversionEngine) -> None:
    with pytest.raises(ValueError, match="not streaming-eligible"):
        engine.convert_stream(
            io.BytesIO(_traj(2)),
            source_format_id="extxyz",
            target_format_id="poscar",
            output=io.BytesIO(),
        )


class _LossyStreamExporter(ExporterPlugin):
    """A streaming extXYZ-writing target that declares it *cannot* express forces — so a source
    carrying forces routes them to ``removed`` and strict mode must refuse without acknowledgement.
    It reuses the real extXYZ exporter for the bytes; only its capability declaration lies."""

    format_id = "lossy_stream"
    format_name = "Lossy streaming target"
    version = "0.1.0"

    def __init__(self) -> None:
        self._inner = ExtxyzExporter()

    def export(self, canonical: object, stream: BinaryIO) -> None:  # pragma: no cover - unused
        self._inner.export(canonical, stream)  # type: ignore[arg-type]

    def supports_streaming(self) -> bool:
        return True

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        export_stream(self._inner, header, frames, stream)

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="write",
            fields={"atoms.symbols": full, "atoms.positions": full},
            max_frames=None,
            required_fields=["atoms.symbols", "atoms.positions"],
            native_coordinate_system="cartesian",
        )


def test_convert_stream_strict_refuses_unacknowledged_loss() -> None:
    registry = Registry()
    registry.register_parser(ExtxyzParser())
    registry.register_exporter(_LossyStreamExporter())
    engine = ConversionEngine(registry)
    assert engine.streaming_eligible("extxyz", "lossy_stream") is True

    out = io.BytesIO()
    result = engine.convert_stream(
        io.BytesIO(_traj(2)),  # carries forces, which the target drops
        source_format_id="extxyz",
        target_format_id="lossy_stream",
        output=out,
        mode="strict",
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "UNACKNOWLEDGED_LOSS"
    assert result.validation is None


def test_convert_stream_completes_and_validates(engine: ConversionEngine) -> None:
    out = io.BytesIO()
    result = engine.convert_stream(
        io.BytesIO(_traj(4)),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=out,
        source_filename="t.xyz",
    )
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert out.getvalue()  # bytes were streamed to the provided output
