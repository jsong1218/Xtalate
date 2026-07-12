"""Parser / exporter plugin ABCs (MASTER_SPEC Part 3 §2).

First-party and third-party formats implement the *same* interface; core formats hold no
privileged API (this is what makes the SDK trustworthy, §2). A parser reads exactly one
native format and never reads another, calls another parser, writes files, or defaults an
absent field (P2, P3). An exporter is the mirror: reads a Canonical Object, writes exactly
one native format, never reads native files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO

from xtalate.schema import CanonicalObject
from xtalate.sdk.capabilities import FormatCapabilities
from xtalate.sdk.results import ParseResult


class ParserPlugin(ABC):
    """Base class for all format parsers (Part 3 §2)."""

    format_id: str  # Stable machine identifier, e.g. "xyz". Lowercase, unique.
    format_name: str  # Human-readable, e.g. "Plain XYZ".
    version: str  # Parser version, recorded in Provenance.history[].parser_version.
    file_extensions: tuple[str, ...] = ()  # Hints only; never authoritative (POSCAR has none).

    @abstractmethod
    def sniff(self, head: bytes, filename: str | None) -> float:
        """Confidence in [0.0, 1.0] that ``head`` (first <= 64 KiB) is this format. Must be
        cheap, side-effect free, and must never raise. 0.0 = definitely not; 1.0 = unambiguous."""

    @abstractmethod
    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Read the full file and return a ParseResult (§5). MUST honor the absence
        convention (Part 2 §2: no defaulting), convert to canonical units, record source
        units / original_coordinate_system, and append a "parse" ConversionRecord."""

    @abstractmethod
    def capabilities(self) -> FormatCapabilities:
        """This format's read-side capability declaration (§4). Assembled into the matrix
        at registry load; never hand-maintained centrally."""


class ExporterPlugin(ABC):
    """Base class for all format exporters (Part 3 §2; behavioral rules in Part 4)."""

    format_id: str
    format_name: str
    version: str

    @abstractmethod
    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        """Write ``canonical`` to ``stream`` in this exporter's native format. Never reads
        native files. Transformations (unit/coordinate/sign) are reported by the Conversion
        Engine, not performed silently."""

    def atom_permutation(self, canonical: CanonicalObject) -> list[int] | None:
        """The atom reordering this exporter applies on write, or ``None`` for no reordering.

        When present, it is a list ``perm`` of length N where output position *i* holds source
        atom ``perm[i]`` — the **permutation map** the Validation Engine needs to compare species
        and positions after a reorder (Part 5 §2, ``species_preservation``). An exporter that
        reorders atoms (e.g. POSCAR groups them by element) MUST override this so the map is
        derived from the *same* grouping it writes; the default identity is correct for exporters
        that preserve source order. Additive to the frozen ``export`` contract (DECISIONS.md D23),
        so existing/third-party exporters keep working unchanged."""
        return None

    @abstractmethod
    def capabilities(self) -> FormatCapabilities:
        """This format's write-side capability declaration (§4)."""
