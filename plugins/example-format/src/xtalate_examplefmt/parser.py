"""Parser for ``exfmt`` — the example-format reference plugin (M36).

``exfmt`` is a deliberately small, self-describing text format that still carries a real
*loss*: a magic header, an **optional** free-text label line, then one
``<symbol> <x> <y> <z>`` row per atom, Cartesian angstrom, a single frame::

    EXFMT 1
    # water monomer, optimized geometry
    O  0.0     0.0  0.0
    H  0.9584  0.0  0.0
    H -0.2396  0.9273  0.0

The label line is optional; when present it is read into
``user_metadata.custom_per_frame['exfmt:label']`` (Part 2 §6.1 carry-through). The *exporter*
declares it cannot write that label back, so a converted file reports the label ``removed`` —
the honest, non-``FULL`` declaration a real format needs and the lesson the all-``FULL`` toyfmt
fixture cannot teach. Every other canonical field is ``None`` — the absence convention (P3),
honored here exactly as a first-party parser honors it.

This module imports **only** the frozen public surface — ``xtalate.sdk`` and ``xtalate.schema``
— and nothing from ``xtalate.parsers``/``xtalate.capabilities`` or any other internal layer,
which is what makes it a faithful third-party example. An ``import-linter`` ``forbidden``
contract in the parent repo proves it.
"""

from __future__ import annotations

from typing import BinaryIO

import numpy as np
from pydantic import ValidationError

from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Frame,
    Provenance,
    UserMetadata,
)
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

FORMAT_ID = "exfmt"
MAGIC = "EXFMT"
LABEL_KEY = "exfmt:label"


class ExampleFormatParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "Example Format (reference plugin)"
    version = "1.0.0"
    file_extensions = (".exfmt",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        # Cheap, never raises (Part 3 §2): the magic header is unambiguous, so a match is a
        # certainty; the extension is only a weak fallback for a truncated head.
        text = head.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                if line.split()[:1] == [MAGIC]:
                    return 1.0
                break  # first non-blank line is not the header — not exfmt
        if filename is not None and filename.lower().endswith(".exfmt"):
            return 0.4
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        try:
            text = stream.read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="EXFMT_ENCODING",
                        message=f"file is not valid UTF-8: {exc}",
                    )
                ]
            ) from exc
        lines = text.splitlines()

        # The first non-blank line must be the magic header.
        idx = 0
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines) or lines[idx].split()[:1] != [MAGIC]:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="EXFMT_BAD_MAGIC",
                        message=f"expected a {MAGIC!r} header line",
                        location="line 1",
                    )
                ]
            )
        idx += 1

        # Optional label line: the next non-blank line, if it begins with '#'. An empty label
        # ("# ") is a *present* empty string, not an absence (P3) — carried verbatim.
        label: str | None = None
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines) and lines[idx].lstrip().startswith("#"):
            label = lines[idx].lstrip()[1:].strip()
            idx += 1

        symbols: list[str] = []
        positions: list[list[float]] = []
        for lineno in range(idx, len(lines)):
            line = lines[lineno]
            if not line.strip():
                continue  # tolerate blank separators between atom rows
            parts = line.split()
            if len(parts) != 4:
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="EXFMT_MALFORMED_ATOM",
                            message=f"expected '<symbol> x y z', found {line!r}",
                            location=f"line {lineno + 1}",
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
                            code="EXFMT_MALFORMED_COORDINATE",
                            message=f"non-numeric coordinate: {line!r}",
                            location=f"line {lineno + 1}",
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
                        code="EXFMT_EMPTY",
                        message="file has a header but no atom rows",
                    )
                ]
            )

        try:
            atoms = AtomsBlock(symbols=symbols, positions=np.asarray(positions, dtype=float))
        except ValidationError as exc:
            # The canonical schema is the authority on valid symbols and shapes; surface its
            # rejection as an attributed parse error rather than letting a pydantic traceback
            # escape the plugin boundary (Part 3 §5).
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="EXFMT_INVALID_ATOMS",
                        message=f"atom block rejected by the canonical schema: {exc}",
                    )
                ]
            ) from exc

        frame = Frame(index=0, atoms=atoms)
        # A per-frame label is one value per frame (§3.10); a single-frame file carries a
        # one-element list. Absent label -> the container stays empty (absence, not "").
        user_metadata = (
            UserMetadata(custom_per_frame={LABEL_KEY: [label]})
            if label is not None
            else UserMetadata()
        )
        parse_notes = ["parsed by the xtalate-example-format reference plugin"]
        if label is not None:
            parse_notes.append(
                "label line preserved in user_metadata.custom_per_frame['exfmt:label']"
            )
        provenance = Provenance(
            source_filename=filename,
            source_format=FORMAT_ID,
            source_units={"positions": "angstrom"},
            original_coordinate_system="cartesian",
            parse_notes=parse_notes,
        )
        return ParseResult(
            canonical=CanonicalObject(
                frames=[frame], provenance=provenance, user_metadata=user_metadata
            )
        )

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                # exfmt reads the optional label perfectly — FULL on the read side. The write
                # side (see the exporter) declares it NONE, which is exactly what turns a
                # carried label into an honest `removed` entry on conversion.
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Optional free-text label line (exfmt:label), one per frame.",
                ),
            },
            max_frames=1,
            required_fields=[],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
