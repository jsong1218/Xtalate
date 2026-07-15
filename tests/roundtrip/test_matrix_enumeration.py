"""The round-trip suite enumerates its pairs *from the registry*, not a hand-list (Part 8 §2.4,
the M9 "done means").

Proof: registering a brand-new dummy format into a fresh registry grows the enumerated targets,
sources, and pair list — and the comparable subspace machinery answers for it — with **zero edits**
to any suite module. This is the mechanical guarantee behind **P6**: a third-party plugin format
joins the matrix the moment it registers.
"""

from __future__ import annotations

from typing import BinaryIO

from tests.roundtrip import _matrix
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    ParseResult,
    ParserPlugin,
)

_DUMMY = "dummy_fmt"
_FULL = FieldCapability(level=CapabilityLevel.FULL)


class _DummyParser(ParserPlugin):
    format_id = _DUMMY
    format_name = "Dummy Test Format"
    version = "0"

    def sniff(self, head: bytes, filename: str | None) -> float:
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:  # pragma: no cover
        raise NotImplementedError("dummy format is registration-only")

    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
            format_id=_DUMMY,
            format_name=self.format_name,
            direction="read",
            fields={"atoms.positions": _FULL, "atoms.symbols": _FULL},
            native_coordinate_system="cartesian",
        )


class _DummyExporter(ExporterPlugin):
    format_id = _DUMMY
    format_name = "Dummy Test Format"
    version = "0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:  # pragma: no cover
        raise NotImplementedError("dummy format is registration-only")

    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
            format_id=_DUMMY,
            format_name=self.format_name,
            direction="write",
            fields={"atoms.positions": _FULL, "atoms.symbols": _FULL},
            native_coordinate_system="cartesian",
        )


def test_registering_a_format_grows_the_matrix_with_zero_suite_edits() -> None:
    base = default_registry()
    base_targets = set(_matrix.writeable_targets(base))
    base_sources = set(_matrix.readable_sources(base))
    base_pairs = set(_matrix.two_hop_pairs(base))
    assert _DUMMY not in base_targets and _DUMMY not in base_sources

    grown = default_registry()
    grown.register_parser(_DummyParser())
    grown.register_exporter(_DummyExporter())

    # The registry-derived enumerators pick the new format up unchanged.
    assert set(_matrix.writeable_targets(grown)) == base_targets | {_DUMMY}
    assert set(_matrix.readable_sources(grown)) == base_sources | {_DUMMY}

    # Every golden-backed source now pairs with the new target — exactly the new pairs, no others.
    grown_pairs = set(_matrix.two_hop_pairs(grown))
    expected_new = {(src, _DUMMY) for src in _matrix.source_formats_with_golden()}
    assert grown_pairs == base_pairs | expected_new
    # The dummy has no golden source fixture, so it never becomes a *source* pair (target-only,
    # exactly like `contcar` until a golden lands for it).
    assert not any(src == _DUMMY for src, _ in grown_pairs)


def test_comparable_subspace_answers_for_a_new_format() -> None:
    grown = default_registry()
    grown.register_parser(_DummyParser())
    grown.register_exporter(_DummyExporter())
    matrix = grown.capability_matrix()

    # Matrix-driven, not hand-listed: the dummy declared positions/symbols FULL both ways, so they
    # fall in the comparable subspace against any format that also round-trips them fully.
    subspace = _matrix.comparable_subspace(matrix, "xyz", _DUMMY)
    assert subspace == {"atoms.positions", "atoms.symbols"}
