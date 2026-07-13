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
                # Plain XYZ has exactly one free-text comment line per frame — it can hold the
                # `xyz:comment` key and nothing else. Declaring the container FULL would predict a
                # foreign per-frame key (e.g. an extXYZ `config_type` on an extXYZ→XYZ conversion)
                # Preserved, then silently drop it in `export` — a validation false-fail and a real
                # loss. PARTIAL + `writable_custom_keys` makes the split honest: `xyz:comment` is
                # Preserved, every other per-frame key is Removed (Part 3 §4.2).
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only the free-text comment line (xyz:comment), one per frame; other "
                    "per-frame keys cannot be expressed by plain XYZ.",
                ),
            },
            max_frames=None,
            required_fields=["atoms.symbols", "atoms.positions"],
            writable_custom_keys={"user_metadata.custom_per_frame": [_COMMENT_KEY]},
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
