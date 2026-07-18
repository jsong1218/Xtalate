"""VASP XDATCAR parser (MASTER_SPEC Part 3 §3; v0.3 M13).

The format that motivated frame-chunked processing (M12): a VASP MD trajectory, routinely
10⁴ configurations of the same atoms. Hand-rolled, consistent with the POSCAR family
(DECISIONS.md D7) — the grammar is small and the fractional→Cartesian conversion and the
per-frame-cell (NpT) reading both want hand control.

**Streaming-first.** ``parse_stream`` is the real implementation and ``parse`` is defined as
``materialize(parse_stream(...))``, so the whole-file and streamed readings cannot diverge —
they are one code path, not two that must be kept in step (M12; DECISIONS.md D56). Peak memory
tracks one configuration block, never the trajectory length.

Format-defined facts handled at parse time and recorded rather than guessed (Part 3 §5 rule 3):

* **Direct → Cartesian at the boundary** using *each frame's* lattice (§4);
  ``original_coordinate_system`` records what the source used.
* **``pbc = (T,T,T)``** by format definition, as a ``parse_notes`` entry (§3 n.3) — never
  invented per-file.
* **``trajectory.timestep = None``** (§3 n.5). XDATCAR numbers its configurations but declares
  no time axis, and the canonical model's absence convention (P3) says so plainly: the source
  did not contain a timestep. Inventing VASP's ``POTIM`` default here would be exactly the
  silent fabrication the mission forbids (P1/P4).
* **Fixed-cell and per-frame-cell (NpT) forms.** VASP repeats the whole 7-line header before
  each configuration when the cell varies; the per-frame cell is the format's distinctive
  canonical feature, so ``Frame.cell`` legitimately varies frame to frame.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

import numpy as np
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance
from xtalate.schema import SCHEMA_VERSION, AtomsBlock, Cell, Frame, TrajectoryMetadata
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

FORMAT_ID = "xdatcar"

_COMMENT_KEY = "xdatcar:comment"
_PBC_NOTE = (
    "pbc set to (true,true,true) per XDATCAR format definition (format-defined, not assumed)."
)
_COORD_NOTE = "Direct coordinates converted to Cartesian using each frame's lattice matrix (§4)."
_CARTESIAN_NOTE = "Cartesian coordinates scaled by each frame's scaling factor (§4)."
# The scaling factor is folded into the lattice (§4) and recorded as a provenance note, not as a
# presence-bearing field — the same routing POSCAR settled on (DECISIONS.md D34): a scale already
# reflected in the reconstructed lattice is not independent information the target must carry.
_SCALE_NOTE_PREFIX = (
    "scaling factor folded into each frame's lattice vectors (§4); source value at frame 0: "
)


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


def _all_ints(tokens: list[str]) -> bool:
    if not tokens:
        return False
    try:
        for t in tokens:
            int(t)
    except ValueError:
        return False
    return True


def _is_config_line(line: str) -> bool:
    """Whether ``line`` is a configuration marker (``Direct configuration=     1``).

    Keyed off the word "configuration" rather than the leading token, because the leading token
    is the *coordinate mode* (``Direct``/``Cartesian``) and both spellings occur. This is the
    discriminator between the fixed-cell form (config lines back to back) and the NpT form (a
    whole header repeated before each config), so it must not confuse a config line with a title.
    """
    return "configuration" in line.lower()


@dataclass
class _Block:
    """One configuration's header state: the lattice it was written under and its coordinate mode.

    For the fixed-cell form this is established once and reused; for the NpT form VASP restates
    it before every configuration, so each frame carries its own.
    """

    lattice: np.ndarray
    fractional: bool
    symbols: list[str]
    scale_token: str
    # The scale multiplier is folded into ``lattice`` above, which covers fractional coordinates
    # (they multiply through the lattice), but Cartesian rows are in scaled units directly and
    # need it applied on their own (§4) — same rule as POSCAR.
    multiplier: float


class XdatcarParser(ParserPlugin):
    """VASP XDATCAR reader (Part 3 §3).

    ``conventional_name`` is VASP's fixed filename (XDATCAR); an exact match returns sniff
    confidence 1.0 (Part 3 §6.1), mirroring how POSCAR/CONTCAR identify themselves. On a
    nameless file the structural signature — a POSCAR-shaped header followed by a
    ``... configuration=`` line — is what distinguishes XDATCAR from POSCAR, which has
    coordinates immediately after the counts line.
    """

    version = "0.1.0"

    def __init__(self) -> None:
        self.format_id = FORMAT_ID
        self.format_name = "VASP XDATCAR"
        self.file_extensions = ()  # XDATCAR is a conventional *name*, not an extension.

    # -- sniff -------------------------------------------------------------------------

    def sniff(self, head: bytes, filename: str | None) -> float:
        if filename is not None and filename == "XDATCAR":
            return 1.0  # VASP's exact conventional name selects this reading (§6.1)
        text = head.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) < 8:
            return 0.0
        try:
            float(lines[1].strip())
            for row in lines[2:5]:
                if len(row.split()) != 3:
                    return 0.0
                [float(t) for t in row.split()]
        except ValueError:
            return 0.0
        if _all_ints(lines[5].split()) or not _all_ints(lines[6].split()):
            return 0.0  # need a VASP-5 species line (line 6) + counts (line 7)
        # The discriminator against POSCAR: a configuration marker where POSCAR has coordinates.
        return 0.95 if _is_config_line(lines[7]) else 0.0

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object.

        Deliberately *not* a second implementation: ``materialize`` is the named fallback M12
        introduced (DECISIONS.md D56), and routing ``parse`` through it means a streamed and a
        whole-file XDATCAR reading are the same code, so they cannot disagree about a frame,
        a warning, or the trajectory container.
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
        """Recover an XDATCAR whose tail is a torn write by keeping the valid prefix
        (``truncate_at_last_valid_frame`` → ``truncate``, Part 4 §3.3; the M13 half of D56).

        The characteristic XDATCAR failure: an MD run killed while writing configuration *k*, so
        frames 0..k-1 are perfectly good science sitting behind a corrupt tail. Only ``truncate``
        reaches here — ``abort`` is the caller declining to recover, handled in the orchestration
        (``conversion.parse_recovery``), because a parse that produced no object is a parse error,
        not a completed conversion.

        Re-reads through the *same* streaming path in truncate mode, so the kept prefix is read by
        exactly the code that reads an intact file, and the truncation is recorded as a warning
        ``ParseIssue`` — the dropped tail is never silent (P1).
        """
        if hint != "truncate_at_last_valid_frame":
            raise NotImplementedError(f"xdatcar parse_recover does not handle hint {hint!r}")
        if choice != "truncate":
            raise NotImplementedError(
                f"xdatcar parse_recover applies only the 'truncate' choice (got {choice!r})"
            )
        frame_stream = self.parse_stream(stream, filename=filename, truncate=True)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(
        self, stream: BinaryIO, *, filename: str | None, truncate: bool = False
    ) -> FrameStream:
        """Header-eager, configuration-lazy XDATCAR parse (M12; Part 3 §2).

        Reads the file **one configuration block at a time** off the raw byte stream, so peak
        memory tracks the resident frame rather than the frame count — the property XDATCAR
        exists to exercise. The 7-line header is read eagerly to establish the lattice, the
        species/counts (hence the atom count), and the object-level ``provenance``; every
        configuration is yielded lazily.

        ``parse_notes`` are established from the header — true of the fixed-cell and NpT forms
        alike, since both restate the *same* facts (scale folded in, Direct→Cartesian, format-
        defined pbc) per frame. The Conversion Report carries no ``parse_notes``, so this can
        never affect report truth (standing rule 3).

        ``truncate`` is the internal switch ``parse_recover`` sets to apply the caller's
        ``truncate_at_last_valid_frame`` choice: a recoverable error mid-stream then *ends* the
        stream at the last good frame (recording a warning) instead of propagating. It is not part
        of the ``ParserPlugin.parse_stream`` contract — callers reach it through ``parse_recover``,
        so the default read stays the honest one that refuses a corrupt file.
        """
        issues: list[ParseIssue] = []
        lines = _Lines(stream)

        title = _require(lines, "file is empty", location="line 1").rstrip("\n")
        block = _read_header(lines, first=True)
        n_atoms = len(block.symbols)

        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="fractional" if block.fractional else "cartesian",
            source_units={
                "positions": "fractional" if block.fractional else "angstrom",
                "lattice_vectors": "angstrom",
            },
            parse_notes=[
                _COORD_NOTE if block.fractional else _CARTESIAN_NOTE,
                _PBC_NOTE,
                f"{_SCALE_NOTE_PREFIX}{block.scale_token}",
            ],
        )
        custom_global: dict[str, JsonValue] = {_COMMENT_KEY: title}
        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=provenance,
            # XDATCAR numbers configurations but declares no time axis (§3 n.5): absent, not zero.
            trajectory=TrajectoryMetadata(timestep=None),
            custom_global=custom_global,
        )

        def _frames() -> Iterator[StreamFrame]:
            yielded = 0
            try:
                for frame in _configurations(lines, block, n_atoms, issues):
                    yielded += 1
                    yield frame
            except ParseError as exc:
                # Truncate mode: a *recoverable* mid-stream error ends the stream at the last good
                # frame instead of propagating (the caller asked for the valid prefix via
                # parse_recover). Two guards keep this honest: only errors the parser itself marked
                # recoverable are swallowed — a structurally wrong file (variable atom count, bad
                # symbol) still raises, because that is not a torn tail — and the truncation is
                # recorded as a warning so the dropped frames are never silent (P1).
                issue = exc.issues[0]
                if not (truncate and issue.recovery_hint == "truncate_at_last_valid_frame"):
                    raise
                if yielded == 0:
                    # Truncating to nothing is not a recovery: there is no valid prefix to keep, so
                    # the honest answer is the original error. Letting it through would hand the
                    # caller an empty frame list, which the schema rejects with a raw pydantic
                    # ValidationError — escaping the Part 3 §5 error contract entirely.
                    raise
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="XDATCAR_TRUNCATED",
                        message=(
                            f"kept the valid configurations and discarded the corrupt tail "
                            f"({issue.code}: {issue.message})"
                        ),
                        location=issue.location,
                    )
                )

        return FrameStream(header, _frames(), issues=issues)

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Per-frame cells are read for the NpT form (a repeated header before "
                    "each configuration); the fixed-cell form gives every frame the same lattice.",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Always (T,T,T) by format definition; XDATCAR carries no explicit PBC.",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Title line."
                ),
            },
            max_frames=None,  # the point of the format: an unbounded configuration count
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="both",
            lossy_notes=[],
        )


# --- reading machinery ------------------------------------------------------------------


def _line_reader(stream: BinaryIO) -> Iterator[str]:
    """Yield decoded lines off the raw byte stream one at a time.

    Line-at-a-time (rather than ``stream.read()``) is what keeps the streaming parser's peak
    memory bounded by a configuration block instead of the trajectory. A non-UTF-8 byte raises
    the structured ``ParseError`` of Part 3 §5 at the point of failure — mid-stream for a byte
    in a later frame, exactly as the error contract requires.
    """
    while True:
        raw = stream.readline()
        if raw == b"":
            return
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                "XDATCAR_ENCODING_ERROR",
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); xdatcar is a text "
                "format",
            ) from exc


class _Lines:
    """A single-pass line source with one line of pushback.

    The pushback is what lets a block boundary be classified without ever holding more than a
    line: at the end of a configuration the next line may be a configuration marker (the
    fixed-cell form), a title (the NpT form restating its header), a *blank* title, or trailing
    whitespace at end of file — and telling the last two apart needs one line of lookahead that
    must then be handed back to the header reader unconsumed.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._iter = _line_reader(stream)
        self._pushed: str | None = None

    def next(self) -> str | None:
        if self._pushed is not None:
            line, self._pushed = self._pushed, None
            return line
        return next(self._iter, None)

    def push(self, line: str) -> None:
        self._pushed = line

    def next_significant(self) -> str | None:
        """The next non-blank line (right-stripped of its newline), or ``None`` at end of file."""
        while (line := self.next()) is not None:
            if line.strip() != "":
                return line.rstrip("\n")
        return None


def _require(lines: _Lines, message: str, *, location: str, hint: str | None = None) -> str:
    line = lines.next()
    if line is None:
        raise _error("XDATCAR_MALFORMED", message, location=location, hint=hint)
    return line


def _classify_boundary(lines: _Lines) -> str:
    """What follows a finished configuration: ``"eof"``, ``"config"``, or ``"header"``.

    Consumes exactly what that answer implies — the configuration marker for ``"config"``, the
    title line for ``"header"``, nothing for ``"eof"`` — leaving ``lines`` positioned for the
    caller. The subtle case is a **blank** line, which is genuinely ambiguous in this format: it
    can be trailing whitespace at end of file, a separator some writer padded a block with, or
    the *empty title* of a restated header (an XDATCAR converted from a source that carried no
    title has exactly that). One line of lookahead settles it — a configuration marker after the
    blanks means they were separators; anything else means the blank was a title and the line we
    peeked is the restated header's scale, so it is pushed back unconsumed.
    """
    first = lines.next()
    if first is None:
        return "eof"
    if first.strip() != "":
        return "config" if _is_config_line(first) else "header"  # non-blank: marker or title
    peeked = lines.next_significant()
    if peeked is None:
        return "eof"  # trailing blank line(s)
    if _is_config_line(peeked):
        return "config"  # the blank(s) were separators before the next configuration
    lines.push(peeked)
    return "header"  # the blank was an empty title; `peeked` is the restated scale line


def _floats(line: str, *, location: str) -> list[float]:
    try:
        return [float(t) for t in line.split()]
    except ValueError as exc:
        raise _error(
            "XDATCAR_MALFORMED",
            f"expected numeric values, found {line.strip()!r}",
            location=location,
        ) from exc


def _read_header(lines: _Lines, *, first: bool, index: int = 0) -> _Block:
    """Read the 6 lines after the title (scale, 3 lattice rows, species, counts) plus the
    configuration marker, returning the block state the following coordinates are read under.

    The same routine serves the file's opening header and each header the NpT form restates, so
    a per-frame cell is read by exactly the code that reads the first one. The caller consumes
    the title line before calling; ``index`` names the frame whose restated header this is, for
    error locations.
    """
    where = "header" if first else f"restated header at frame {index}"
    # A *restated* header that runs off the end of the file is a torn write — an NpT run killed
    # partway through emitting frame `index`'s header — so it is recoverable in the same sense a
    # half-written configuration is: the frames before it are good science. The opening header
    # running out has no valid prefix to keep, so it stays a plain refusal.
    torn = None if first else "truncate_at_last_valid_frame"

    scale_token = _require(
        lines, f"file ended before the scaling factor ({where})", location="line 2", hint=torn
    ).strip()
    try:
        scale = float(scale_token)
    except ValueError as exc:
        raise _error(
            "XDATCAR_MALFORMED",
            f"scaling factor is not numeric: {scale_token!r} ({where})",
            location="line 2",
        ) from exc
    if scale == 0.0:
        raise _error(
            "XDATCAR_MALFORMED", f"scaling factor must be non-zero ({where})", location="line 2"
        )

    rows: list[list[float]] = []
    for k in range(3):
        row = _floats(
            _require(
                lines,
                f"file ended inside the lattice ({where})",
                location=f"line {3 + k}",
                hint=torn,
            ),
            location=f"line {3 + k}",
        )
        if len(row) != 3:
            raise _error(
                "XDATCAR_MALFORMED",
                f"lattice row must have 3 components, found {len(row)} ({where})",
                location=f"line {3 + k}",
            )
        rows.append(row)
    raw_lattice = np.asarray(rows, dtype=float)
    # A negative scale is a target *volume*: the multiplier makes det(lattice) == |scale| (§4).
    if scale < 0:
        det = float(np.linalg.det(raw_lattice))
        if det == 0.0:
            raise _error(
                "XDATCAR_MALFORMED",
                f"degenerate lattice (zero volume) ({where})",
                location="line 3",
            )
        multiplier = (abs(scale) / abs(det)) ** (1.0 / 3.0)
    else:
        multiplier = scale
    lattice = multiplier * raw_lattice

    species_line = _require(
        lines, f"file ended before the species line ({where})", location="line 6", hint=torn
    ).split()
    if not species_line or _all_ints(species_line):
        # XDATCAR states its species in the header (§3 n.1), so a well-formed file never needs
        # `missing_species`. A VASP-4-shaped header (counts, no symbols) is malformed *for this
        # format* rather than a recovery opportunity — refused, never filled with placeholders.
        raise _error(
            "XDATCAR_MALFORMED",
            f"expected a species line of element symbols, found {' '.join(species_line)!r}; "
            "XDATCAR declares its species in the header (Part 3 §3 n.1)",
            location="line 6",
        )
    for sym in species_line:
        if not is_valid_symbol(sym):
            raise _error(
                "XDATCAR_INVALID_SYMBOL",
                f"unknown element symbol {sym!r} on the species line (Part 2 §3.3) ({where})",
                location="line 6",
            )
    count_tokens = _require(
        lines, f"file ended before the counts line ({where})", location="line 7", hint=torn
    ).split()
    if not _all_ints(count_tokens) or len(count_tokens) != len(species_line):
        raise _error(
            "XDATCAR_MALFORMED",
            f"expected {len(species_line)} integer counts to match species {species_line}, "
            f"found {' '.join(count_tokens)!r} ({where})",
            location="line 7",
        )
    counts = [int(t) for t in count_tokens]
    symbols: list[str] = []
    for sym, c in zip(species_line, counts, strict=True):
        symbols.extend([sym] * c)
    if not symbols:
        raise _error(
            "XDATCAR_MALFORMED", f"header declares zero atoms ({where})", location="line 7"
        )

    config = lines.next_significant()
    if config is None:
        raise _error(
            "XDATCAR_MALFORMED",
            f"file ended before the first configuration marker ({where})",
            location="line 8",
        )
    if not _is_config_line(config):
        raise _error(
            "XDATCAR_MALFORMED",
            f"expected a configuration marker (e.g. 'Direct configuration=     1'), found "
            f"{config.strip()!r} ({where})",
            location="line 8",
        )
    # VASP's coordinate-mode rule (§4), identical to POSCAR's: a marker beginning with C/K is
    # Cartesian; everything else — 'Direct', or anything unexpected — is Direct/fractional.
    # Keying off 'd' instead would silently misread a fractional file as Cartesian Å.
    mode_char = config.strip()[:1].lower()
    return _Block(
        lattice=lattice,
        fractional=mode_char not in ("c", "k"),
        symbols=symbols,
        scale_token=scale_token,
        multiplier=multiplier,
    )


def _configurations(
    lines: _Lines, first_block: _Block, n_atoms: int, issues: list[ParseIssue]
) -> Iterator[StreamFrame]:
    """Yield every configuration in the file, one at a time, following the cell form as it goes.

    Split out of ``parse_stream`` so the truncate-recovery wrapper can catch a recoverable error
    around the *whole* loop without the loop itself knowing anything about recovery: reading and
    recovering stay separate concerns, and the frames a recovered read keeps are produced by
    exactly this code.
    """
    current = first_block
    index = 0
    while True:
        yield _read_configuration(lines, current, index, n_atoms)
        index += 1
        boundary = _classify_boundary(lines)
        if boundary == "eof":
            return
        if boundary == "config":
            continue  # fixed-cell form: the next configuration under the same lattice
        # NpT form: VASP restated the whole header, so this frame has its own cell.
        current = _read_header(lines, first=False, index=index)
        if len(current.symbols) != n_atoms:
            raise _error(
                "XDATCAR_VARIABLE_ATOM_COUNT",
                f"configuration {index} restates a header with {len(current.symbols)} atoms but "
                f"configuration 0 has {n_atoms}; the canonical model requires a constant atom "
                "count across frames (Part 2 §3.2)",
                location=f"frame {index}",
            )
        if current.symbols != first_block.symbols:
            raise _error(
                "XDATCAR_VARIABLE_SPECIES",
                f"configuration {index} restates a header whose species order differs from "
                "configuration 0's; the canonical model requires a constant atom identity across "
                "frames (Part 2 §3.2)",
                location=f"frame {index}",
            )
        if current.fractional != first_block.fractional:
            # Each block is still *read* under its own mode, so nothing is misconverted; what would
            # be wrong is provenance.original_coordinate_system (established from frame 0) silently
            # standing for the whole file. Say so instead (P1).
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="XDATCAR_MIXED_COORDINATE_MODE",
                    message=(
                        f"configuration {index} is "
                        f"{'Direct' if current.fractional else 'Cartesian'} but configuration 0 is "
                        f"{'Direct' if first_block.fractional else 'Cartesian'}; each frame is "
                        "converted under its own mode, but "
                        "provenance.original_coordinate_system records frame 0's"
                    ),
                    location=f"frame {index}",
                )
            )


def _read_configuration(
    lines: _Lines,
    block: _Block,
    index: int,
    n_atoms: int,
) -> StreamFrame:
    """Read one configuration's ``n_atoms`` coordinate rows into a ``StreamFrame``.

    A block that ends before its coordinates complete is a **recoverable** ``ParseError``
    carrying ``recovery_hint="truncate_at_last_valid_frame"`` (Part 4 §3.3) — the characteristic
    XDATCAR corruption, an MD run killed mid-write. Recoverable because the frames already read
    are perfectly good science; the user chooses whether to keep them, and the choice is recorded
    as an Assumption rather than applied silently (P4).
    """
    coords: list[list[float]] = []
    for a in range(n_atoms):
        line = lines.next()
        if line is None or line.strip() == "":
            raise _error(
                "XDATCAR_TRUNCATED_CONFIGURATION",
                f"configuration {index} declares {n_atoms} atoms but the block ended after {a}; "
                "the file appears truncated mid-configuration",
                location=f"frame {index}",
                hint="truncate_at_last_valid_frame",
            )
        parts = line.split()
        # A short or non-numeric coordinate row inside a configuration block is the *same* torn
        # write as a missing one — a process killed partway through a line leaves "0.1 0.0" or
        # "0.1 0.0 0.0000\x00" just as readily as it leaves the line out. Both therefore carry the
        # recoverable hint: the frames already read are unaffected, so keeping them is a choice the
        # user is entitled to make rather than a judgement the parser makes for them.
        if len(parts) < 3:
            raise _error(
                "XDATCAR_TRUNCATED_CONFIGURATION",
                f"coordinate line in configuration {index} has fewer than 3 components: "
                f"{line.strip()!r}; the line appears to have been truncated mid-write",
                location=f"frame {index}",
                hint="truncate_at_last_valid_frame",
            )
        try:
            coords.append([float(parts[0]), float(parts[1]), float(parts[2])])
        except ValueError as exc:
            raise _error(
                "XDATCAR_TRUNCATED_CONFIGURATION",
                f"non-numeric coordinate in configuration {index}: {line.strip()!r}",
                location=f"frame {index}",
                hint="truncate_at_last_valid_frame",
            ) from exc

    raw = np.asarray(coords, dtype=float)
    # Convert at the parser boundary (§4) using *this frame's* lattice — which is what makes the
    # NpT form read correctly: a frame's fractional coordinates mean nothing without its own cell.
    positions = raw @ block.lattice if block.fractional else raw * block.multiplier
    return StreamFrame(
        frame=Frame(
            index=index,
            atoms=AtomsBlock(symbols=list(block.symbols), positions=positions),
            cell=Cell(lattice_vectors=block.lattice, pbc=(True, True, True)),
        )
    )


def make_xdatcar_parser() -> XdatcarParser:
    return XdatcarParser()
