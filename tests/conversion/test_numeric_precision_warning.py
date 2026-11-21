from __future__ import annotations

import io

from xtalate.conversion import ConversionEngine
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.parsers.xyz import XyzParser
from xtalate.registry import default_registry

XYZ = b"2\nwater-ish\nH 0.0 0.0 0.0\nO 0.0 0.0 0.96\n"
# extXYZ with a float per-atom custom column "foo" (real extXYZ Properties= grammar)
EXTXYZ_WITH_FOO = (
    b'2\nProperties=species:S:1:pos:R:3:foo:R:1 pbc="F F F"\n'
    b"H 0.0 0.0 0.0 0.5\nO 0.0 0.0 0.96 0.25\n"
)


def _warnings(source: bytes, parser: object, src_id: str, dst_id: str) -> list[str]:
    obj = parser.parse(io.BytesIO(source), filename="a.xyz").canonical  # type: ignore[attr-defined]
    engine = ConversionEngine(default_registry())
    result = engine.convert(
        obj, source_format_id=src_id, target_format_id=dst_id, source_filename="a.xyz"
    )
    return [w.message for w in result.report.warnings if w.code == "NUMERIC_PRECISION_LIMITED"]


def test_positions_to_extxyz_warn_about_eight_decimals() -> None:
    msgs = _warnings(XYZ, XyzParser(), "xyz", "extxyz")
    assert len(msgs) == 1
    assert "Positions" in msgs[0]
    assert "8 decimal" in msgs[0]


def test_custom_float_columns_to_extxyz_are_declared_not_silent() -> None:
    msgs = _warnings(EXTXYZ_WITH_FOO, ExtxyzParser(), "extxyz", "extxyz")
    assert any("Custom per-atom" in m for m in msgs), msgs
    assert any("integer and string columns are exact" in m for m in msgs)


def test_no_precision_warning_for_formats_without_a_declaration() -> None:
    # xyz -> xyz: the plain XYZ exporter declares no numeric_precision.
    assert _warnings(XYZ, XyzParser(), "xyz", "xyz") == []
