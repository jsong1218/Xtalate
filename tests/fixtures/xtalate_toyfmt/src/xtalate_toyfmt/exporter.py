"""Exporter for ``toyfmt`` — the mirror of :mod:`xtalate_toyfmt.parser` (M16B).

Writes exactly what the toy format can express — element symbols and Cartesian positions of a
single frame — and nothing else. Coordinates go out with Python's shortest round-tripping float
``repr`` so ``float64 -> text -> float64`` is exact and identity round-trips are byte-stable.
Fields the format cannot hold are reported as ``removed`` by the Conversion Engine's pre-flight,
never dropped silently here (P1).
"""

from __future__ import annotations

from typing import BinaryIO

from xtalate.schema import CanonicalObject
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
)
from xtalate_toyfmt.parser import FORMAT_ID, MAGIC


class ToyfmtExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "Toy Format (example plugin)"
    version = "0.0.1"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        # Single-frame format: write the first frame. The pre-flight (max_frames=1) reports any
        # dropped trailing frames before this runs, so the write itself loses nothing silently.
        atoms = canonical.frames[0].atoms
        out = [f"{MAGIC} 1"]
        for symbol, pos in zip(atoms.symbols, atoms.positions, strict=True):
            x, y, z = (repr(float(c)) for c in pos)
            out.append(f"{symbol} {x} {y} {z}")
        stream.write(("\n".join(out) + "\n").encode("utf-8"))

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={"atoms.symbols": full, "atoms.positions": full},
            max_frames=1,
            required_fields=["atoms.symbols", "atoms.positions"],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
