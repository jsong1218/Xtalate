"""Plain XYZ parser (MASTER_SPEC Part 3 §3, §8.1).

Hand-rolled (DECISIONS.md D7): the grammar is trivial and hand-rolling avoids importing a
library that would invent defaults we would then have to launder back into absences. XYZ
carries exactly three things — element symbols, Cartesian positions (Å), and a free-text
comment line per frame — and *nothing* else. Every other canonical field is therefore
``None`` on the resulting object; that is the absence convention (Part 2 §2), not a gap to
be filled.

**Streaming-first.** ``parse_stream`` is the real implementation and ``parse`` is defined as
``materialize(parse_stream(...))``, so the whole-file and streamed readings are one code path
and cannot diverge (M12; DECISIONS.md D56). Peak memory tracks one frame, never the trajectory
length — the property the frame cap's count pass (M39-S3) relies on: an over-cap plain-XYZ
trajectory is refused before the frames past the cap are read. One documented streaming nuance
(D56): the reader splits lines on ``\\n``/``\\r\\n`` only, whereas ``splitlines()`` (the old
whole-file path) also recognised bare ``\\r``; a file using bare ``\\r`` line endings is read as
one (malformed) line rather than the frames ``splitlines()`` would have found.

Grammar (one or more concatenated frames)::

    <atom count N>
    <comment: free text, may be empty>
    <symbol> <x> <y> <z>        # N lines
    ...                          # next frame's count, or EOF

Comment lines are information (they routinely hold frame labels / energies as free text),
so they are carried verbatim — one per frame — under
``user_metadata.custom_per_frame["xyz:comment"]`` (Part 3 §6.1 carry-through rule).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO

import numpy as np

from xtalate.parsers._common import build_provenance
from xtalate.schema import SCHEMA_VERSION, AtomsBlock, Frame, TrajectoryMetadata
from xtalate.schema.elements import is_valid_symbol
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)
from xtalate.sdk.streaming import FrameStream, StreamFrame, StreamHeader, materialize

FORMAT_ID = "xyz"
_COMMENT_KEY = "xyz:comment"
# extXYZ (an XYZ superset, Part 3 §3 n.2) puts key=value metadata on the comment line;
# these markers let plain XYZ yield to a future extXYZ parser (M3c) on such files (§6.1).
_EXTXYZ_MARKERS = ("Lattice=", "Properties=")


def _looks_like_coordinate(line: str) -> bool:
    """True if ``line`` is ``<symbol> <float> <float> <float>`` (the XYZ atom row)."""
    parts = line.split()
    if len(parts) < 4:
        return False
    if not is_valid_symbol(parts[0]):
        return False
    try:
        float(parts[1]), float(parts[2]), float(parts[3])
    except ValueError:
        return False
    return True


def _error(
    code: str, message: str, *, location: str | None = None, hint: str | None = None
) -> ParseError:
    return ParseError(
        [
            ParseIssue(
                severity="error",
                code=code,
                message=message,
                location=location,
                recovery_hint=hint,
            )
        ]
    )


def _line_reader(stream: BinaryIO) -> Iterator[str]:
    """Yield decoded lines off the raw byte stream one at a time.

    Line-at-a-time (rather than ``stream.read()``) is what keeps the streaming parser's peak
    memory bounded by one frame instead of the trajectory (M12). A non-UTF-8 byte raises the
    structured ``ParseError`` of Part 3 §5 at the point of failure, exactly like the whole-file
    reader's ``decode_text``; the byte offset named is the one *within the offending line*, since
    a line-at-a-time reader has no file-global offset to report.
    """
    while True:
        raw = stream.readline()
        if raw == b"":
            return
        try:
            yield raw.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise _error(
                "XYZ_ENCODING_ERROR",
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); xyz is a text format",
            ) from exc


class _Lines:
    """A single-pass line source with one line of pushback and physical line numbers.

    ``lineno`` is the 1-based number of the most recently *read* line (a pushed-back line keeps
    its number), so the streaming reader's ``line N`` error locations match the numbering a
    whole-file ``splitlines()`` read would have produced exactly.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._iter = _line_reader(stream)
        self._pushed: str | None = None
        self.lineno = 0

    def next(self) -> str | None:
        if self._pushed is not None:
            pushed = self._pushed
            self._pushed = None
            return pushed
        line = next(self._iter, None)
        if line is not None:
            self.lineno += 1
        return line

    def push(self, line: str) -> None:
        self._pushed = line


def _first_significant(lines: _Lines) -> str | None:
    """The first non-blank line, or ``None`` in a wholly blank/empty file."""
    while (line := lines.next()) is not None:
        if line.strip() != "":
            return line
    return None


class XyzParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "Plain XYZ"
    version = "0.1.0"
    file_extensions = (".xyz",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        # Cheap, never raises (§2): structural check on the first frame only.
        text = head.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            return 0.0
        try:
            count = int(lines[0].strip())
        except ValueError:
            return 0.0  # first line is not an atom count — not XYZ
        if count <= 0:
            return 0.0
        extxyz_comment = False
        if len(lines) < 3:
            # Header parses but we cannot see a coordinate row (tiny head); weak signal,
            # leaned on the .xyz filename hint if present.
            score = 0.4
        else:
            score = 0.9 if _looks_like_coordinate(lines[2]) else 0.3
            extxyz_comment = any(marker in lines[1] for marker in _EXTXYZ_MARKERS)
        if filename is not None and filename.lower().endswith(".xyz"):
            score = max(score, 0.7)
        if extxyz_comment:
            # extXYZ territory (a superset): cap last — after the filename hint, which does
            # not distinguish the two — so the more-expressive parser wins when registered.
            score = min(score, 0.6)
        return score

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object.

        Deliberately *not* a second implementation: ``materialize`` is the named fallback M12
        introduced (DECISIONS.md D56), and routing ``parse`` through it means a streamed and a
        whole-file XYZ reading are the same code, so they cannot disagree about a frame, a
        warning, or the trajectory container.
        """
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def parse_recover(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
    ) -> ParseResult:
        """Recover a trajectory with a corrupt final frame by truncating at the last valid one
        (``truncate_at_last_valid_frame`` → ``truncate``, Part 4 §3.3).

        Only ``truncate`` reaches here — ``abort`` is the caller re-raising the original error, and
        is handled in the orchestration, not the parser. Re-reads through the *same* streaming path
        in truncate mode, so the kept prefix is read by exactly the code that reads an intact file,
        and the truncation is recorded as a warning ``ParseIssue`` so the dropped tail is not
        silent (P1). A re-read that finds nothing corrupt returns the clean parse without
        inventing a truncation record.
        """
        if hint != "truncate_at_last_valid_frame":
            raise NotImplementedError(f"xyz parse_recover does not handle hint {hint!r}")
        if choice != "truncate":
            raise NotImplementedError(
                f"xyz parse_recover applies only the 'truncate' choice (got {choice!r})"
            )
        frame_stream = self.parse_stream(stream, filename=filename, truncate=True)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(
        self, stream: BinaryIO, *, filename: str | None, truncate: bool = False
    ) -> FrameStream:
        """Header-eager, frame-lazy plain XYZ parse (M12; Part 3 §2).

        Reads the file **one frame at a time** off the raw byte stream, so peak memory tracks the
        resident frame, never the frame count — the property the frame cap's count pass (M39-S3)
        relies on: an over-cap trajectory is refused before the frames past the cap are read. The
        object-level header (``provenance``, the trajectory container) depends on nothing per
        frame and is established eagerly; every frame is yielded lazily, each built by the same
        ``_read_one_frame`` grammar the error contract documents (Part 3 §5).

        ``truncate`` is the internal switch ``parse_recover`` sets to apply the caller's
        ``truncate_at_last_valid_frame`` choice: a recoverable error mid-stream then *ends* the
        stream at the last good frame (recording a warning) instead of propagating. It is not part
        of the ``ParserPlugin.parse_stream`` contract — callers reach it through ``parse_recover``,
        so the default read stays the honest one that refuses a corrupt file.
        """
        issues: list[ParseIssue] = []
        lines = _Lines(stream)
        first = _first_significant(lines)
        if first is None:
            raise _error("XYZ_EMPTY", "file contains no frames")
        lines.push(first)

        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=build_provenance(
                format_id=FORMAT_ID,
                filename=filename,
                original_coordinate_system="cartesian",
                source_units={"positions": "angstrom"},
                parse_notes=[
                    "comment lines preserved in user_metadata.custom_per_frame['xyz:comment']"
                ],
            ),
            # A single-frame XYZ is a static structure (trajectory=None, Part 2 §3.2); multiple
            # frames form a trajectory whose source declares no time base (timestep=None, §8.1).
            # ``materialize`` drops the container for a single-frame stream, reproducing the
            # whole-file object exactly.
            trajectory=TrajectoryMetadata(timestep=None),
        )

        def _frames() -> Iterator[StreamFrame]:
            yielded = 0
            try:
                while True:
                    read = self._read_one_frame(lines, yielded)
                    if read is None:
                        return
                    frame, comment = read
                    yielded += 1
                    yield StreamFrame(frame=frame, per_frame_custom={_COMMENT_KEY: comment})
            except ParseError as exc:
                # Truncate mode: a *recoverable* mid-stream error ends the stream at the last good
                # frame instead of propagating (the caller asked for the valid prefix via
                # parse_recover). Two guards keep this honest: only errors the parser itself marked
                # recoverable are swallowed — a structurally wrong file (bad header, invalid
                # symbol) still raises, because that is not a torn tail — and the truncation is
                # recorded as a warning so the dropped frames are never silent (P1).
                issue = exc.issues[0]
                if not (truncate and issue.recovery_hint == "truncate_at_last_valid_frame"):
                    raise
                if yielded == 0:
                    # Truncating to nothing is not a recovery: there is no valid prefix to keep,
                    # so the honest answer is the original error.
                    raise
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="XYZ_TRUNCATED",
                        message=(
                            f"kept frames 0..{yielded - 1} and discarded the corrupt tail "
                            f"beginning at frame {yielded} ({issue.message})"
                        ),
                        location=issue.location,
                    )
                )

        return FrameStream(header, _frames(), issues=issues)

    def _read_one_frame(self, lines: _Lines, frame_index: int) -> tuple[Frame, str] | None:
        """Read the single frame whose count line is next, or ``None`` at a clean end of file.

        Returns the frame and its comment line. Raises the same ``ParseError``s the whole-file
        reader raised, with the same codes, messages, and ``line N`` / ``frame N`` locations
        (Part 3 §5 rule 4) — this *is* that reader now, reading one line at a time. Mid-file
        truncation-recoverable corruption carries
        ``recovery_hint=\"truncate_at_last_valid_frame\"``.
        """
        # Skip blank separators between frames; running out of lines here is a clean end of the
        # trajectory (a wholly blank file was already refused as ``XYZ_EMPTY`` by the eager
        # header check).
        while True:
            line = lines.next()
            if line is None or line.strip() != "":
                break
        if line is None:
            return None
        header = line.strip()
        try:
            count = int(header)
        except ValueError as exc:
            raise _error(
                "XYZ_MALFORMED_HEADER",
                f"expected an integer atom count, found {header!r}",
                location=f"line {lines.lineno}",
            ) from exc
        if count <= 0:
            raise _error(
                "XYZ_MALFORMED_HEADER",
                f"atom count must be positive, found {count}",
                location=f"line {lines.lineno}",
            )
        # Comment line (may be empty; the line must still exist).
        comment = lines.next()
        if comment is None:
            raise _error(
                "XYZ_INCONSISTENT_ATOM_COUNT",
                (
                    f"frame {frame_index} declares {count} atoms but the file ends "
                    "before its comment line and coordinates"
                ),
                location=f"frame {frame_index}",
                hint="truncate_at_last_valid_frame",
            )
        symbols: list[str] = []
        positions: list[list[float]] = []
        for j in range(count):
            row = lines.next()
            if row is None:
                raise _error(
                    "XYZ_INCONSISTENT_ATOM_COUNT",
                    (
                        f"frame {frame_index} declares {count} atoms but only {j} "
                        "coordinate lines are present before end of file"
                    ),
                    location=f"frame {frame_index}",
                    hint="truncate_at_last_valid_frame",
                )
            parts = row.split()
            if len(parts) < 4:
                # Fewer tokens than "<symbol> x y z" means the declared count is wrong:
                # a coordinate row is missing (Part 3 §5 rule 4 — mid-file corruption).
                raise _error(
                    "XYZ_INCONSISTENT_ATOM_COUNT",
                    (
                        f"frame {frame_index} declares {count} atoms but line {lines.lineno} "
                        f"is not a '<symbol> x y z' coordinate row: {row!r}"
                    ),
                    location=f"frame {frame_index}",
                    hint="truncate_at_last_valid_frame",
                )
            symbol = parts[0]
            if not is_valid_symbol(symbol):
                raise _error(
                    "XYZ_INVALID_SYMBOL",
                    (
                        f"unknown element symbol {symbol!r} at line {lines.lineno} "
                        "(use 'X' for a genuinely unknown species, Part 2 §3.3)"
                    ),
                    location=f"line {lines.lineno}",
                )
            try:
                xyz = [float(parts[1]), float(parts[2]), float(parts[3])]
            except ValueError as exc:
                raise _error(
                    "XYZ_MALFORMED_COORDINATE",
                    f"non-numeric coordinate at line {lines.lineno}: {row!r}",
                    location=f"line {lines.lineno}",
                ) from exc
            symbols.append(symbol)
            positions.append(xyz)

        frame = Frame(
            index=frame_index,
            atoms=AtomsBlock(symbols=symbols, positions=np.asarray(positions, dtype=float)),
        )
        return frame, comment

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Free-text comment line, one per frame."
                ),
            },
            max_frames=None,
            required_fields=[],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
