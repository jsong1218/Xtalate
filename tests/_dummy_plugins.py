"""Reusable dummy ParserPlugin/ExporterPlugin for registry and sniffer tests.

Not a test module (no ``test_`` prefix); imported by tests under ``tests/``. Lets a test
declare a format's sniff behaviour and capability fields inline without a real parser.
"""

from __future__ import annotations

from typing import BinaryIO

import numpy as np

from chembridge.schema import AtomsBlock, CanonicalObject, Frame, Provenance
from chembridge.sdk import (
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    ParseResult,
    ParserPlugin,
)


def make_object(source_format: str = "dummy") -> CanonicalObject:
    """A minimal valid single-atom CanonicalObject for parsers to return."""
    return CanonicalObject(
        frames=[
            Frame(index=0, atoms=AtomsBlock(symbols=["O"], positions=np.array([[0.0, 0.0, 0.0]])))
        ],
        provenance=Provenance(
            source_filename=None,
            source_format=source_format,
            original_coordinate_system="cartesian",
        ),
    )


class DummyParser(ParserPlugin):
    """Configurable parser. Sniffs by ``signature`` prefix when given (optionally boosted
    for an exact ``conventional_name`` match — the POSCAR/CONTCAR mechanism), else returns
    a constant ``score``."""

    def __init__(
        self,
        format_id: str = "dummy",
        *,
        score: float = 0.0,
        signature: bytes | None = None,
        conventional_name: str | None = None,
        fields: dict[str, FieldCapability] | None = None,
        required: list[str] | None = None,
    ) -> None:
        self.format_id = format_id
        self.format_name = f"Dummy {format_id}"
        self.version = "0.1.0"
        self.file_extensions = (f".{format_id}",)
        self._score = score
        self._signature = signature
        self._conventional_name = conventional_name
        self._fields = fields or {}
        self._required = required or []

    def sniff(self, head: bytes, filename: str | None) -> float:
        if self._conventional_name is not None and filename == self._conventional_name:
            return 1.0  # exact conventional-name match selects this parser (§6.1)
        if self._signature is not None:
            return 0.95 if head.startswith(self._signature) else 0.0
        return self._score

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        return ParseResult(canonical=make_object(self.format_id))

    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="read",
            fields=self._fields,
            required_fields=self._required,
            native_coordinate_system="cartesian",
        )


class DummyExporter(ExporterPlugin):
    def __init__(
        self,
        format_id: str = "dummy",
        *,
        fields: dict[str, FieldCapability] | None = None,
        required: list[str] | None = None,
        max_frames: int | None = None,
    ) -> None:
        self.format_id = format_id
        self.format_name = f"Dummy {format_id}"
        self.version = "0.1.0"
        self._fields = fields or {}
        self._required = required or []
        self._max_frames = max_frames

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        stream.write(canonical.model_dump_json().encode())

    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="write",
            fields=self._fields,
            required_fields=self._required,
            max_frames=self._max_frames,
            native_coordinate_system="cartesian",
        )
