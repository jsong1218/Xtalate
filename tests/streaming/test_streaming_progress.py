"""convert_stream / convert_stream_select report progress per source frame (QoL Q3)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from xtalate.conversion.engine import ConversionEngine
from xtalate.registry import default_registry

_EXTXYZ_FRAME = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3:forces:R:3 energy={e} config_type=md pbc="T T T"\n'
    "O 0.0 0.0 0.0 0.1 0.0 0.0\n"
    "H 1.0 0.0 0.0 0.0 0.2 0.0\n"
    "H 0.0 1.0 0.0 0.0 0.0 0.3\n"
)
_XDATCAR_HEADER = """cubic cell
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
"""


def _extxyz(n: int) -> bytes:
    return "".join(_EXTXYZ_FRAME.format(e=f"-1.{i}") for i in range(n)).encode()


def _xdatcar(n: int) -> bytes:
    blocks = "".join(
        f"Direct configuration=  {i + 1:>5}\n  {0.01 * i:.6f} 0.0 0.0\n  0.5 0.5 0.5\n"
        for i in range(n)
    )
    return (_XDATCAR_HEADER + blocks).encode()


def _norm(report: Any) -> dict[str, object]:
    d: dict[str, object] = report.model_dump(mode="json")
    d["report_id"] = "X"
    d["created_at"] = "X"
    return d


@pytest.fixture
def engine() -> ConversionEngine:
    return ConversionEngine(default_registry())


def _stream(engine: ConversionEngine, n: int, progress: Any) -> Any:
    return engine.convert_stream(
        io.BytesIO(_extxyz(n)),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=io.BytesIO(),
        source_filename="t.xyz",
        progress=progress,
    )


def test_progress_is_called_once_per_frame_and_is_monotonic(engine: ConversionEngine) -> None:
    seen: list[int] = []
    _stream(engine, 5, seen.append)
    assert seen == [1, 2, 3, 4, 5]


def test_progress_does_not_change_the_report(engine: ConversionEngine) -> None:
    with_cb = _stream(engine, 4, lambda n: None)
    without = _stream(engine, 4, None)
    assert _norm(with_cb.report) == _norm(without.report)


def test_select_progress_counts_every_scanned_frame(engine: ConversionEngine) -> None:
    seen: list[int] = []
    engine.convert_stream_select(
        io.BytesIO(_xdatcar(4)),
        source_format_id="xdatcar",
        target_format_id="poscar",
        output=io.BytesIO(),
        frame_selection={"choice": "last"},
        source_filename="XDATCAR",
        progress=seen.append,
    )
    assert seen == [1, 2, 3, 4]
