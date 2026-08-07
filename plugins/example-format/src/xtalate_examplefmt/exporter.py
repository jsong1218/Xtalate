"""Exporter for ``exfmt`` — the mirror of :mod:`xtalate_examplefmt.parser` (M36).

Writes exactly what the format can express — element symbols and Cartesian positions of a
single frame — and **not** the per-frame label the parser reads. That asymmetry is the point:
the label is declared *unwritable* (``user_metadata.custom_per_frame`` is ``NONE`` on the write
side), so the Conversion Engine's pre-flight reports it ``removed`` before a byte is written
(P1) — never dropped silently here. Coordinates go out with Python's shortest round-tripping
float ``repr`` so ``float64 -> text -> float64`` is exact and identity round-trips are
byte-stable (DECISIONS.md D8).

Imports only the frozen public surface (``xtalate.sdk`` + ``xtalate.schema``).
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
from xtalate_examplefmt.parser import FORMAT_ID, MAGIC


class ExampleFormatExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "Example Format (reference plugin)"
    version = "1.0.0"

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
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                # The honest, non-FULL declaration this reference plugin exists to demonstrate:
                # exfmt reads a per-frame label but writes NONE back, so a present `exfmt:label`
                # is reported `removed` in pre-flight (never predicted-preserved and then
                # silently dropped). Contrast plain XYZ, which declares this container PARTIAL
                # because it CAN write exactly one key (its `xyz:comment` line): NONE and PARTIAL
                # are the two honest shapes of "less than FULL" (Part 3 §4.2).
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.NONE,
                    notes="exfmt cannot write a per-frame label back; the label line is "
                    "read-only and is dropped on export.",
                ),
            },
            max_frames=1,
            required_fields=["atoms.symbols", "atoms.positions"],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
