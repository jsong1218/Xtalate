"""Parser / exporter plugin ABCs (MASTER_SPEC Part 3 §2).

First-party and third-party formats implement the *same* interface; core formats hold no
privileged API (this is what makes the SDK trustworthy, §2). A parser reads exactly one
native format and never reads another, calls another parser, writes files, or defaults an
absent field (P2, P3). An exporter is the mirror: reads a Canonical Object, writes exactly
one native format, never reads native files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, BinaryIO

from xtalate.schema import CanonicalObject
from xtalate.sdk.capabilities import FormatCapabilities
from xtalate.sdk.results import ExporterWarning, ParseResult

if TYPE_CHECKING:
    from xtalate.sdk.streaming import FrameStream, StreamFrame, StreamHeader


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

    def parse_recover(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
        recovery_context: Mapping[str, object] | None = None,
    ) -> ParseResult:
        """Re-parse a file that raised a *recoverable* ``ParseError`` (Part 4 §3.3), applying the
        caller's recovery ``choice`` for the error's ``recovery_hint``.

        Optional (additive to the frozen ``parse`` contract, like
        ``ExporterPlugin.atom_permutation`` — DECISIONS.md D23/D38): a parser overrides it *only* if
        it emits recoverable hints (``supply_species``, ``truncate_at_last_valid_frame``). The
        returned ``ParseResult`` must carry a **warning** ``ParseIssue`` documenting what the
        recovery did, so the outcome is never silent. The caller
        (``conversion.parse_with_recovery``) maps the hint to a scenario, records one
        ``Assumption`` per applied choice, and threads it
        into the Conversion Report; the parser performs only the mechanical re-read. The default
        refuses — a parser that raised a recoverable hint but did not override this is a bug,
        surfaced loudly rather than silently.

        ``recovery_context`` (M48; additive, default ``None``) carries **every** parse-time choice
        the orchestrator has resolved so far for this file, keyed by scenario — each value the same
        ``{"choice", "parameters"}`` spec as ``recovery_choices``. It exists because a single file
        can lack several required facts at once: a LAMMPS *data* file declares neither its unit
        style nor its element symbols (nor its atom style, when the ``Atoms`` comment is absent), so
        it needs ``ambiguous_units`` + ``missing_species`` (+ ``ambiguous_atom_style``) applied
        *together* in one re-read. ``conversion._try_recover`` drives an accumulating loop, adding
        the current scenario to ``recovery_context`` before each call, so a parser that consumes it
        can apply the whole set at once. Parsers that need only one recovery at a time ignore it and
        read ``hint``/``choice``/``parameters`` as before — it is accept-and-ignore for them."""
        raise NotImplementedError(
            f"{type(self).__name__} raised a recoverable parse error (hint {hint!r}) but "
            "implements no parse_recover hook"
        )

    def supports_streaming(self) -> bool:
        """Whether this parser implements ``parse_stream`` (M12). The default ``False`` marks a
        whole-file parser the registry adapts by materializing (``sdk.streaming.stream_of``); a
        streaming parser overrides both this and ``parse_stream`` together."""
        return False

    def parse_stream(self, stream: BinaryIO, *, filename: str | None) -> FrameStream:
        """Parse the header eagerly and yield frames lazily (M12; MASTER_SPEC Part 3 §2).

        Optional and additive to the frozen ``parse`` contract (like ``parse_recover`` and
        ``ExporterPlugin.atom_permutation`` — DECISIONS.md D23/D38/D56). A parser overrides it
        *and* ``supports_streaming`` to gain sub-linear memory on large trajectories; the returned
        ``FrameStream`` must obey the same absence convention (P3) and error contract (Part 3 §5) as
        ``parse`` — its frame generator raises ``ParseError`` at the offending frame and appends
        warning ``ParseIssue``s to ``FrameStream.issues`` as frames are yielded. The default
        refuses, since ``supports_streaming`` gates whether this is ever called."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement streaming parse; call parse() instead, or "
            "adapt via sdk.streaming.stream_of"
        )

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

    def export_warnings(self, canonical: CanonicalObject) -> list[ExporterWarning]:
        """Transformations this exporter will apply on :meth:`export`/``export_stream``, reported
        as Conversion Report Warnings (Part 4 §1 rule 3; DECISIONS.md D151).

        Additive and optional, like ``atom_permutation`` (DECISIONS.md D23) and streaming (D56):
        the default returns no warnings, so existing/third-party exporters keep working unchanged.
        An exporter overrides it only when writing can change *representation* — e.g. extXYZ
        reverses the canonical tension-positive stress to the compression-positive convention its
        ASE-native files carry, and reports ``STRESS_SIGN_CONVENTION_CHANGED``. The engine calls
        this once per conversion with the write-plan-filtered object (``canonical′``) and maps the
        result to ``ReportWarning(source="export")``; the exporter owns the decision, never the
        engine (the engine cannot know which transformations a foreign exporter applies).
        """
        return []

    def unrepresentable(self, canonical: CanonicalObject) -> str | None:
        """Why this exporter cannot represent ``canonical``'s *values*, or ``None`` when every value
        is representable (Part 4 §1; DECISIONS.md D179).

        The Capability Matrix predicts loss at *field* granularity — whether a format can hold a
        field at all. Some targets accept a field's type but not every value: a LAMMPS dump holds a
        lattice, but only in LAMMPS's restricted-triclinic form, and refuses any other cell rather
        than silently rotate it (D43); it likewise holds velocities, but its constant-column layout
        cannot carry them on only *some* frames of a trajectory. Those are value-level facts the
        capability diff cannot see, so the engine asks the exporter directly — once per conversion,
        on the write-plan-filtered object (``canonical′``) it is about to write, the same object
        ``export_warnings`` sees. A returned string is the plain-language reason and produces a
        clean ``UNREPRESENTABLE_VALUE`` refusal (a completed HTTP-200 refused report, never an
        export-time crash; P1); ``None`` lets the export proceed. Additive and optional like
        ``export_warnings`` (D151) and
        ``atom_permutation`` (D23): the default returns ``None``, so existing and third-party
        exporters are unaffected. It reports; it never mutates ``canonical``."""
        return None

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

    def reparse_recovery(
        self, canonical: CanonicalObject
    ) -> Mapping[str, dict[str, object]] | None:
        """The recovery context the Validation Engine must apply to re-parse **this exporter's own
        output**, or ``None`` when the output is self-describing (M48-S2, D182).

        Validation re-parses the written bytes and diffs them against the source object (Part 5 §2).
        Almost every format's output is self-describing — a dump writes its ``ITEM: UNITS`` header
        and an element column, POSCAR/CIF/XYZ carry their own labels — so the re-parse is a bare
        ``parse`` and this returns ``None`` (the default). A **LAMMPS data** file is the exception:
        it declares neither a unit system nor element symbols (atoms are numeric types only), so its
        output cannot re-parse without the same ``ambiguous_units`` + ``missing_species`` choices
        the conversion already resolved. This hook hands the Validation Engine that context —
        derived from the object the exporter wrote, so it reproduces exactly the write — the engine
        drives the target parser's ``parse_recover`` with it instead of ``parse``. The applied
        choices are already recorded Assumptions in the Conversion Report, so re-applying them on
        re-read is the expected mechanism, not a new finding.

        Return value: the ``{scenario: {"choice", "parameters"}}`` map ``parse_recover`` consumes as
        its ``recovery_context`` (the M48 SDK seam). Additive to the frozen ``export`` contract
        (like ``atom_permutation``); existing/third-party exporters keep the self-describing
        default."""
        return None

    def supports_streaming(self) -> bool:
        """Whether this exporter implements ``export_stream`` (M12). Default ``False`` marks a
        whole-file exporter the engine adapts by materializing before ``export``."""
        return False

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        """Write a frame stream to ``stream`` frame by frame (M12), holding at most a chunk of
        frames resident. Optional and additive to the frozen ``export`` contract (DECISIONS.md D56).

        The exporter is handed the pre-flight-filtered frames (the ``canonical′`` write plan already
        applied per frame), so it writes exactly what it is given and fabricates nothing for absent
        fields (Part 4 §1 rule 2), identically to ``export``. The default refuses;
        ``supports_streaming`` gates whether it is called."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement streaming export; call export() instead"
        )

    @abstractmethod
    def capabilities(self) -> FormatCapabilities:
        """This format's write-side capability declaration (§4)."""
