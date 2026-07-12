"""Plain XYZ exporter (MASTER_SPEC Part 3 §3, Part 4 §1).

The mirror of ``parsers.xyz``: it writes exactly what plain XYZ can express — element
symbols, Cartesian positions, and the per-frame comment line — and nothing else. Fields
the format cannot hold (cell, velocities, energies, ...) are *not* this exporter's concern
to lose quietly: the Conversion Engine's capability pre-flight (Part 4) reports them as
``removed`` before a byte is written. Coordinates are emitted with Python's shortest
round-tripping float ``repr`` (DECISIONS.md D8), so ``float64 → text → float64`` is lossless
and identity round-trips are exact.
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

FORMAT_ID = "xyz"
_COMMENT_KEY = "xyz:comment"


class XyzExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "Plain XYZ"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        comments = canonical.user_metadata.custom_per_frame.get(_COMMENT_KEY)
        out: list[str] = []
        for i, frame in enumerate(canonical.frames):
            atoms = frame.atoms
            out.append(str(len(atoms.symbols)))
            # Per-frame comment carried through on parse; empty string when the source had none.
            comment = ""
            if comments is not None and i < len(comments):
                value = comments[i]
                comment = value if isinstance(value, str) else str(value)
            out.append(comment)
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
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Free-text comment line, one per frame."
                ),
            },
            max_frames=None,
            required_fields=["atoms.symbols", "atoms.positions"],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
