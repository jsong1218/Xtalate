"""The identity theorem under variable N (M73).

Standing rule 3 says the streamed Conversion Report must equal the materialized one, byte for
byte of output — "chunking changes memory, never truth" (M12). M72 relocated ``custom_per_atom``
onto each frame and M73 relocated it off ``StreamHeader`` onto each ``StreamFrame.frame``, so a
trajectory whose frames have *different* atom counts must still round-trip identically through the
streaming and materialized paths.

This is ``xfail`` until M73-S4 retires the extXYZ constant-N reader refusal; the parse currently
refuses a variable-N trajectory before either path can run. S4 flips the marker off.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from xtalate.conversion.engine import ConversionEngine
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.registry import default_registry

_FRAME_3 = (
    "3\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3 energy=-1.0 pbc="T T T"\n'
    "O 0.0 0.0 0.0\n"
    "H 1.0 0.0 0.0\n"
    "H 0.0 1.0 0.0\n"
)
_FRAME_2 = (
    "2\n"
    'Lattice="5.0 0.0 0.0 0.0 5.0 0.0 0.0 0.0 5.0" '
    'Properties=species:S:1:pos:R:3 energy=-2.0 pbc="T T T"\n'
    "O 0.0 0.0 0.0\n"
    "H 1.0 0.0 0.0\n"
)

_VARIABLE_N = (_FRAME_3 + _FRAME_2).encode()


def _norm(report: Any) -> dict[str, object]:
    d: dict[str, object] = report.model_dump(mode="json")
    d["report_id"] = "X"
    d["created_at"] = "X"
    return d


@pytest.mark.xfail(
    reason="variable-N extXYZ reader refusal retired in M73-S4; identity re-proven then",
    strict=False,
)
def test_streamed_report_equals_materialized_variable_n() -> None:
    engine = ConversionEngine(default_registry())
    src = ExtxyzParser().parse(io.BytesIO(_VARIABLE_N), filename="t.xyz").canonical
    materialized = engine.convert(
        src, source_format_id="extxyz", target_format_id="extxyz", source_filename="t.xyz"
    )
    out = io.BytesIO()
    streamed = engine.convert_stream(
        io.BytesIO(_VARIABLE_N),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=out,
        source_filename="t.xyz",
    )
    assert _norm(streamed.report) == _norm(materialized.report)
    assert out.getvalue() == materialized.output
