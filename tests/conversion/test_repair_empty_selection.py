"""An empty select_frames selection is a RepairError from the engine, with a message naming it."""

from __future__ import annotations

import io

import pytest

from xtalate.conversion.engine import ConversionEngine
from xtalate.registry import default_registry
from xtalate.repair import RepairError, RepairRequest

FOUR_FRAMES = b"".join(
    f"2\nframe {i}\nO {i}.0 0.0 0.0\nH {i}.0 1.0 0.0\n".encode() for i in range(4)
)


def test_empty_selection_raises_repair_error_naming_the_selection() -> None:
    registry = default_registry()
    parsed = registry.get_parser("xyz").parse(io.BytesIO(FOUR_FRAMES), filename="t.xyz").canonical
    engine = ConversionEngine(registry)
    with pytest.raises(RepairError, match="selects no frames"):
        engine.convert(
            parsed,
            source_format_id="xyz",
            target_format_id="extxyz",
            source_filename="t.xyz",
            repairs=[RepairRequest(operation="select_frames", parameters={"start": 9, "stop": 12})],
        )
