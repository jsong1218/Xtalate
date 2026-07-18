"""Parser for ``toyfmt`` — the example plugin's toy format (M16B).

``toyfmt`` is deliberately the simplest format that still carries real scientific data: a magic
header line, then one ``<symbol> <x> <y> <z>`` row per atom, Cartesian angstrom, a single frame::

    TOYFMT 1
    O 0.0 0.0 0.0
    H 0.9584 0.0 0.0

Every other canonical field is therefore ``None`` — the absence convention (P3), honored here
exactly as a first-party parser honors it. This file uses only the public SDK and schema; it
imports nothing from ``xtalate.parsers`` or any other internal layer, which is what makes it a
faithful third-party example.
"""

from __future__ import annotations

from typing import BinaryIO

import numpy as np

from xtalate.schema import AtomsBlock, CanonicalObject, Frame, Provenance
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

FORMAT_ID = "toyfmt"
MAGIC = "TOYFMT"


class ToyfmtParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "Toy Format (example plugin)"
    version = "0.0.1"
    file_extensions = (".toy",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        # Cheap, never raises (Part 3 §2): the magic header is unambiguous, so a match is a
        # certainty; the extension is only a weak fallback for a truncated head.
        text = head.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if lines and lines[0].strip().startswith(MAGIC):
            return 1.0
        if filename is not None and filename.lower().endswith(".toy"):
            return 0.4
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        text = stream.read().decode("utf-8", errors="strict")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines or not lines[0].strip().startswith(MAGIC):
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="TOYFMT_BAD_MAGIC",
                        message=f"expected a {MAGIC!r} header line",
                        location="line 1",
                    )
                ]
            )

        symbols: list[str] = []
        positions: list[list[float]] = []
        for lineno, line in enumerate(lines[1:], start=2):
            parts = line.split()
            if len(parts) != 4:
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="TOYFMT_MALFORMED_ATOM",
                            message=f"expected '<symbol> x y z', found {line!r}",
                            location=f"line {lineno}",
                        )
                    ]
                )
            try:
                xyz = [float(parts[1]), float(parts[2]), float(parts[3])]
            except ValueError as exc:
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="TOYFMT_MALFORMED_COORDINATE",
                            message=f"non-numeric coordinate at line {lineno}: {line!r}",
                            location=f"line {lineno}",
                        )
                    ]
                ) from exc
            symbols.append(parts[0])
            positions.append(xyz)

        if not symbols:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="TOYFMT_EMPTY",
                        message="file has a header but no atom rows",
                    )
                ]
            )

        frame = Frame(
            index=0,
            atoms=AtomsBlock(symbols=symbols, positions=np.asarray(positions, dtype=float)),
        )
        provenance = Provenance(
            source_filename=filename,
            source_format=FORMAT_ID,
            source_units={"positions": "angstrom"},
            original_coordinate_system="cartesian",
            parse_notes=["parsed by the xtalate-toyfmt example plugin (M16B)"],
        )
        return ParseResult(canonical=CanonicalObject(frames=[frame], provenance=provenance))

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={"atoms.symbols": full, "atoms.positions": full},
            max_frames=1,
            required_fields=[],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
