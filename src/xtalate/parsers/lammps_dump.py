"""LAMMPS dump parser (MASTER_SPEC Part 3 §3; v1.3 M46-S2).

The text ``dump`` output of a LAMMPS run — the first **full read+write** format added since
v0.3's CIF, shipped here as its parser half (the exporter is M47's first deliverable; this is
a within-milestone parser-first split, **not** the vasprun/OUTCAR source-never-target seam,
D159). A dump is a sequence of per-snapshot blocks:

    ITEM: TIMESTEP
    <step>
    ITEM: NUMBER OF ATOMS
    <n>
    [ITEM: UNITS <style>]                 (only with `dump_modify units yes`)
    ITEM: BOX BOUNDS [xy xz yz] [xflag yflag zflag]
    <bounds rows>
    ITEM: ATOMS <column names…>
    <n data rows>

**Streaming-first** (``parse_stream`` is the real implementation; ``parse`` is
``materialize`` of it — the D56 one-code-path guarantee) because dumps share XDATCAR's 10⁴-frame
scale: peak memory tracks one frame block, never the trajectory.

Honesty on the ordinary axes, per the M46 plan and Part 3 §3 n.19:

* **Declared units honored, undeclared refused.** An ``ITEM: UNITS`` header (when present) is
  honored, the style recorded in ``parse_notes``, and **no scenario fires** — the
  declared-vs-ambiguous contrast. A missing header raises the recoverable
  ``LAMMPSDUMP_AMBIGUOUS_UNITS`` issue (``recovery_hint="ambiguous_units"``); the conversion
  refuses until the caller names a style (Part 4 §3.3, D174). A declared style outside the
  hand-verified table (``metal``/``real``/``si``) is not an ambiguity to resolve — it refuses
  as unsupported, never guessed.
* **Absent velocities stay ``None``** (P3): a dump without ``vx vy vz`` columns reads
  ``dynamics.velocities = None``, never zeros.
* **Generic unmapped columns are carried, never dropped** — any ``compute``/``fix`` output
  column outside the known set lands in ``user_metadata.custom_per_atom["lammps_dump:<name>"]``
  with the warning ``LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED`` (the extXYZ
  ``_collect_custom_columns`` precedent, verbatim). ``custom_per_atom`` is object-level (Part 2
  §3.10), so a column whose values *vary* across frames cannot be represented losslessly: frame
  0 is carried and ``LAMMPSDUMP_PER_FRAME_COLUMN_NOT_REPRESENTABLE`` warns once per diverging
  column (the extXYZ streaming consistency check, same shape).
* **Image flags are a specific, named carry (M46-S3).** A complete ``ix iy iz`` family is
  recognized *specifically* — distinct from the generic carry — and lands in
  ``user_metadata.custom_per_atom["lammps_dump:image_flags"]`` (a ``(N, 3)`` array) with the
  warning ``LAMMPSDUMP_IMAGE_FLAGS_CARRIED``, which states the coordinate convention in force
  alongside (wrapped Cartesian / scaled / unwrapped — the two facts are only useful together).
  The flags are **never applied on parse** (D43 — an unrequested transform that would discard
  the wrapped form the source chose); the pre-flight diff predicts the unwrapping loss when
  such a source targets a format that cannot hold them (Part 3 §4; the named capability dimension).
  A partial ``ix``/``iy``/``iz`` family is malformed, refused.
* **The constant-N boundary is a measured refusal.** A dump whose atom count varies across
  frames (grand-canonical, deposition, evaporation) raises
  ``LAMMPSDUMP_VARIABLE_ATOM_COUNT`` naming the first diverging frame and listing the per-frame
  counts seen — the accumulating, user-visible evidence file for v2.0's variable-N schema
  (Part 2 §3.2). Never truncated, never padded.
* **Typed atoms resolve through the existing ``missing_species`` scenario** (Part 3 §7.2): a
  numeric ``type`` column without a ``species_map`` preset raises the recoverable
  ``LAMMPSDUMP_MISSING_SPECIES`` issue (``recovery_hint="supply_species"``, the same hint the
  VASP-4 POSCAR path uses); an element-labeled dump needs no scenario. The shared ``_lammps``
  core does the map validation and the unit/box/coordinate conversion (S1).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import BinaryIO, cast

import numpy as np

from xtalate.parsers._common import build_provenance
from xtalate.parsers._lammps import (
    Box,
    CoordinateColumns,
    box_from_bounds,
    coordinate_note,
    is_element_column,
    resolve_coordinate_columns,
    resolve_species,
    scaled_to_cartesian,
)
from xtalate.parsers._lammps import (
    unit_style as lookup_unit_style,
)
from xtalate.parsers._lammps.units import UnitStyle
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Frame,
    TrajectoryMetadata,
)
from xtalate.sdk import (
    IMAGE_FLAGS_CARRY_KEY,
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)
from xtalate.sdk.streaming import FrameStream, StreamFrame, StreamHeader, materialize

FORMAT_ID = "lammps_dump"

#: The per-frame custom key the dump's step *number* rides under. The canonical
#: ``trajectory.timestep`` is a time in fs; a dump declares step numbers and no dt, so the
#: index cannot be converted to a time and is carried verbatim instead (P3, P1).
_STEP_KEY = "lammps_dump:timestep"
#: The custom-array key the original numeric type column rides under (frame 0 values, the
#: canonical per-atom first-dim-N contract): the symbols resolved from a ``species_map`` do
#: not by themselves preserve the source's type numbering, so the numbers are carried.
_TYPE_KEY = "lammps_dump:type"
_ID_KEY = "lammps_dump:id"
_CUSTOM_PREFIX = "lammps_dump:"

# Issue codes (Part 3 §5; the recoverable ones carry recovery_hints).
_EMPTY = "LAMMPSDUMP_EMPTY"
_ENCODING = "LAMMPSDUMP_ENCODING_ERROR"
_MALFORMED = "LAMMPSDUMP_MALFORMED_HEADER"
_AMBIGUOUS_UNITS = "LAMMPSDUMP_AMBIGUOUS_UNITS"
_UNSUPPORTED_UNITS = "LAMMPSDUMP_UNSUPPORTED_UNITS"
_MISSING_SPECIES = "LAMMPSDUMP_MISSING_SPECIES"
_NO_SPECIES_COLUMN = "LAMMPSDUMP_NO_SPECIES_COLUMN"
_VARIABLE_ATOM_COUNT = "LAMMPSDUMP_VARIABLE_ATOM_COUNT"
_VARIABLE_SPECIES = "LAMMPSDUMP_VARIABLE_SPECIES"
_UNMAPPED_CARRIED = "LAMMPSDUMP_UNMAPPED_COLUMN_CARRIED"
_IMAGE_FLAGS_CARRIED = "LAMMPSDUMP_IMAGE_FLAGS_CARRIED"
_PER_FRAME_COLUMN = "LAMMPSDUMP_PER_FRAME_COLUMN_NOT_REPRESENTABLE"
_UNITS_INTERPRETED = "LAMMPSDUMP_UNITS_INTERPRETED"
_SPECIES_SUPPLIED = "LAMMPSDUMP_SPECIES_SUPPLIED"

_UNITS_HINT = "ambiguous_units"
_SPECIES_HINT = "supply_species"

#: The coordinate families the dump writes (x/xs/xu semantics — S1's resolver).
_COORD_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("x", "y", "z"),
    ("xs", "ys", "zs"),
    ("xu", "yu", "zu"),
)
_VELOCITY_COLUMNS = ("vx", "vy", "vz")
#: The wrapped-coordinate bookkeeping columns (M46-S3): recognized *specifically*, distinct
#: from the generic unmapped-column carry, and carried to the named image-flags payload.
_IMAGE_FLAG_COLUMNS = ("ix", "iy", "iz")

#: The columns the parser recognizes as its own (S2). The image-flag columns ix/iy/iz are
#: deliberately NOT here: they are handled by the specific image-flag carry (S3), never the
#: generic unmapped-column path.
_KNOWN_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "type",
        *[name for family in _COORD_FAMILIES for name in family],
        *_VELOCITY_COLUMNS,
    }
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


def _line_reader(stream: BinaryIO) -> Iterator[str]:
    """Yield decoded lines off the raw byte stream one at a time (the XDATCAR machinery,
    shared verbatim: line-at-a-time keeps peak memory bounded by one frame block)."""
    while True:
        raw = stream.readline()
        if raw == b"":
            return
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                _ENCODING,
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); lammps_dump is a "
                "text format",
            ) from exc


class _Lines:
    """A single-pass line source (the XDATCAR helper, verbatim shape)."""

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
        """The next non-blank line, or ``None`` at end of file."""
        while (line := self.next()) is not None:
            if line.strip() != "":
                return line.rstrip("\n")
        return None


def _require(lines: _Lines, message: str, *, location: str, hint: str | None = None) -> str:
    line = lines.next()
    if line is None:
        raise _error(_MALFORMED, message, location=location, hint=hint)
    return line


#: The ITEM keywords a dump can declare, longest-first — matched longest-first in
#: ``_header_line`` so the multi-word items (``NUMBER OF ATOMS``, ``BOX BOUNDS``) are not
#: split at their first space.
_ITEMS: tuple[str, ...] = ("NUMBER OF ATOMS", "BOX BOUNDS", "TIMESTEP", "UNITS", "ATOMS")


def _header_line(line: str) -> tuple[str, str] | None:
    """Split an ``ITEM: …`` line into ``(item, rest)``, or ``None`` for a non-ITEM line.

    The item keyword is matched longest-first against the known dump items, so a multi-word
    item like ``NUMBER OF ATOMS`` is not truncated at its first space; ``rest`` is everything
    after the keyword (the unit style, the box flags/tilts, or the column names)."""
    if not line.startswith("ITEM:"):
        return None
    stripped = line[len("ITEM:") :].strip()
    if not stripped:
        return None
    for keyword in _ITEMS:
        if stripped == keyword:
            return keyword, ""
        if stripped.startswith(keyword + " "):
            return keyword, stripped[len(keyword) + 1 :].strip()
    item, _, rest = stripped.partition(" ")
    return item, rest.strip()


def _ints(line: str, *, location: str, what: str) -> int:
    try:
        return int(line.strip())
    except ValueError as exc:
        raise _error(
            _MALFORMED,
            f"expected an integer {what}, found {line.strip()!r}",
            location=location,
        ) from exc


def _floats(tokens: Sequence[str], *, location: str, count: int) -> list[float]:
    if len(tokens) != count:
        raise _error(
            _MALFORMED,
            f"expected {count} numeric values, found {len(tokens)}: {' '.join(tokens)!r}",
            location=location,
        )
    try:
        return [float(t) for t in tokens]
    except ValueError as exc:
        raise _error(
            _MALFORMED,
            f"expected numeric values, found {' '.join(tokens)!r}",
            location=location,
        ) from exc


@dataclass(frozen=True)
class _BlockHeader:
    """One snapshot's header state: step number, atom count, units, box, and column names.

    Everything the data rows need to be interpreted, read *before* the rows. The per-snapshot
    box makes the NpT form (a varying cell) read correctly frame by frame, exactly as
    XDATCAR's per-frame lattice does.
    """

    step: int
    n_atoms: int
    unit_declared: bool  # ITEM: UNITS present in the file
    unit_style: UnitStyle | None  # the style in force (declared or recovery-applied)
    box: Box
    pbc: tuple[bool, bool, bool]
    columns: list[str]
    location: str  # "frame N" for error messages


def _read_block_header(
    lines: _Lines,
    *,
    unit_style: UnitStyle | None,
    frame_index: int,
) -> _BlockHeader:
    """Read one ``ITEM: TIMESTEP`` … ``ITEM: ATOMS <columns>`` block header.

    ``unit_style`` is the recovery-applied style when the caller re-reads under an
    ``ambiguous_units`` choice; ``None`` means honor the file's own declaration (or refuse).
    """
    where = f"frame {frame_index}"
    parsed = _header_line(
        _require(lines, f"file ended before {where}'s TIMESTEP item", location=where)
    )
    item = parsed[0] if parsed is not None else None
    if item != "TIMESTEP":
        raise _error(_MALFORMED, f"expected 'ITEM: TIMESTEP', found {item!r}", location=where)
    step = _ints(
        _require(lines, f"file ended after {where}'s TIMESTEP", location=where),
        location=where,
        what="timestep",
    )
    parsed = _header_line(
        _require(lines, f"file ended before {where}'s NUMBER OF ATOMS item", location=where)
    )
    item = parsed[0] if parsed is not None else None
    if item != "NUMBER OF ATOMS":
        raise _error(
            _MALFORMED, f"expected 'ITEM: NUMBER OF ATOMS', found {item!r}", location=where
        )
    n_atoms = _ints(
        _require(lines, f"file ended after {where}'s atom count", location=where),
        location=where,
        what="atom count",
    )
    if n_atoms <= 0:
        raise _error(
            _MALFORMED,
            f"{where} declares {n_atoms} atoms; a dump needs at least one",
            location=where,
        )

    # Optional ITEM: UNITS — the declared-vs-ambiguous contrast (Part 3 §3 n.19).
    unit_declared = False
    declared_style: UnitStyle | None = None
    peeked = lines.next()
    if peeked is not None:
        parsed = _header_line(peeked.rstrip("\n"))
        if parsed is not None and parsed[0] == "UNITS":
            unit_declared = True
            tokens = parsed[1].split()
            if len(tokens) != 1:
                raise _error(
                    _MALFORMED,
                    f"{where} declares units as {' '.join(tokens)!r}; expected one style",
                    location=where,
                )
            declared_style = lookup_unit_style(tokens[0])
            if declared_style is None:
                raise _error(
                    _UNSUPPORTED_UNITS,
                    f"{where} declares unit style {tokens[0]!r}, which the hand-verified "
                    "conversion tables do not cover (metal/real/si only, M46-S1); the file "
                    "cannot be converted to canonical Å/fs/eV",
                    location=where,
                )
            peeked = lines.next()

    if unit_style is not None and declared_style is not None:
        raise _error(
            _MALFORMED,
            f"{where} declares ITEM: UNITS {declared_style.code} but the recovery re-read was "
            "asked to apply a style; a file either declares its units or it does not",
            location=where,
        )
    effective = unit_style if unit_style is not None else declared_style

    # ITEM: BOX BOUNDS [xy xz yz] [xflag yflag zflag] + three rows.
    if peeked is None:
        raise _error(_MALFORMED, f"file ended before {where}'s BOX BOUNDS item", location=where)
    parsed = _header_line(peeked.rstrip("\n"))
    if parsed is None or parsed[0] != "BOX BOUNDS":
        raise _error(
            _MALFORMED, f"expected 'ITEM: BOX BOUNDS', found {peeked.strip()!r}", location=where
        )
    tokens = parsed[1].split()
    triclinic = tokens[:3] == ["xy", "xz", "yz"]
    flags = tokens[3:] if triclinic else tokens
    if len(flags) != 3:
        raise _error(
            _MALFORMED,
            f"{where}'s BOX BOUNDS header must carry the boundary flags (e.g. 'pp pp pp'); "
            f"found {' '.join(tokens)!r}",
            location=where,
        )
    pbc = (flags[0][:1] == "p", flags[1][:1] == "p", flags[2][:1] == "p")
    rows: list[list[float]] = []
    for _ in range(3):
        row = _floats(
            _require(lines, f"file ended inside {where}'s box bounds", location=where).split(),
            location=where,
            count=3 if triclinic else 2,
        )
        rows.append(row)
    if triclinic:
        box = box_from_bounds(
            rows[0][0],
            rows[0][1],
            rows[1][0],
            rows[1][1],
            rows[2][0],
            rows[2][1],
            xy=rows[0][2],
            xz=rows[1][2],
            yz=rows[2][2],
        )
    else:
        box = box_from_bounds(
            rows[0][0], rows[0][1], rows[1][0], rows[1][1], rows[2][0], rows[2][1]
        )

    item_line = _require(lines, f"file ended before {where}'s ATOMS item", location=where)
    parsed = _header_line(item_line.rstrip("\n"))
    if parsed is None or parsed[0] != "ATOMS":
        raise _error(
            _MALFORMED,
            f"expected 'ITEM: ATOMS <columns>', found {item_line.strip()!r}",
            location=where,
        )
    columns = parsed[1].split()
    if not columns:
        raise _error(
            _MALFORMED, f"{where} declares no per-atom columns after 'ITEM: ATOMS'", location=where
        )

    return _BlockHeader(
        step=step,
        n_atoms=n_atoms,
        unit_declared=unit_declared,
        unit_style=effective,
        box=box,
        pbc=pbc,
        columns=columns,
        location=where,
    )


def _read_data_rows(lines: _Lines, header: _BlockHeader) -> list[list[str]]:
    """Read one snapshot's ``n_atoms`` data rows (token lists, untyped — columns are
    interpreted by name afterwards, so a numeric column and an element column read side by
    side)."""
    rows: list[list[str]] = []
    for a in range(header.n_atoms):
        line = lines.next()
        if line is None or line.strip() == "":
            raise _error(
                _MALFORMED,
                f"{header.location} declares {header.n_atoms} atoms but the block ended after "
                f"{a} data rows",
                location=header.location,
            )
        tokens = line.split()
        if len(tokens) != len(header.columns):
            raise _error(
                _MALFORMED,
                f"{header.location} data row has {len(tokens)} values, expected "
                f"{len(header.columns)} for columns {header.columns}: {line.strip()!r}",
                location=header.location,
            )
        rows.append(tokens)
    return rows


def _column_index(header: _BlockHeader, name: str) -> int:
    try:
        return header.columns.index(name)
    except ValueError:
        raise _error(
            _MALFORMED,
            f"{header.location} is missing its {name!r} column (columns: {header.columns})",
            location=header.location,
        ) from None


def _column_floats(rows: list[list[str]], index: int, header: _BlockHeader) -> np.ndarray:
    out = np.empty(len(rows), dtype=np.float64)
    for a, row in enumerate(rows):
        try:
            out[a] = float(row[index])
        except ValueError:
            raise _error(
                _MALFORMED,
                f"{header.location} {header.columns[index]!r} column value {row[index]!r} at "
                f"atom {a} is not numeric",
                location=header.location,
            ) from None
    return out


def _column_strings(rows: list[list[str]], index: int) -> list[str]:
    return [row[index] for row in rows]


class LammpsDumpParser(ParserPlugin):
    """LAMMPS text dump reader (Part 3 §3; M46-S2)."""

    version = "0.1.0"

    def __init__(self) -> None:
        self.format_id = FORMAT_ID
        self.format_name = "LAMMPS dump (text)"
        self.file_extensions = (".dump", ".lammpstrj")

    # -- sniff -------------------------------------------------------------------------

    def sniff(self, head: bytes, filename: str | None) -> float:
        # The format is unambiguous from its first line: no other text format starts with
        # "ITEM: TIMESTEP" (Part 3 §6.1). The extension is a hint only, never consulted.
        return 1.0 if head.startswith(b"ITEM: TIMESTEP") else 0.0

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56)."""
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
        """Re-read under a parse-time recovery choice (Part 4 §3.3).

        ``ambiguous_units`` → apply the chosen style's conversion factors; ``supply_species``
        → apply the caller's ``species_map`` (a type→symbol map / ordered list / CLI string)
        or ``upload_reference`` (the per-atom symbols of a matching reference structure) to the
        numeric type column. Either way the re-read goes through the *same* streaming code path
        the ordinary parse uses, and the recovery is recorded with a warning ``ParseIssue``
        (never silent, P1).
        """
        if hint == _UNITS_HINT:
            style = lookup_unit_style(choice)
            if style is None:
                raise _error(
                    _UNSUPPORTED_UNITS,
                    f"parse_recover(ambiguous_units) cannot apply unknown style {choice!r}",
                )
            frame_stream = self.parse_stream(stream, filename=filename, unit_style=style)
            canonical, issues = materialize(frame_stream)
            note = ParseIssue(
                severity="warning",
                code=_UNITS_INTERPRETED,
                message=(
                    f"unit style interpreted as {choice} ({style.summary}) per recovery "
                    "choice; all positions, velocities, and box bounds converted from that "
                    "basis"
                ),
            )
            return ParseResult(canonical=canonical, issues=[*issues, note])
        if hint == _SPECIES_HINT:
            if choice == "species_map":
                species_map = _recover_species_map(parameters)
                wording = "a type→symbol species_map preset"
            elif choice == "upload_reference":
                species_map = _reference_species_map(parameters)
                wording = "the atom symbols of a matching reference structure"
            else:
                raise _error(
                    _MISSING_SPECIES,
                    f"supply_species has no choice {choice!r} "
                    "(offered: species_map, upload_reference)",
                    hint=_SPECIES_HINT,
                )
            frame_stream = self.parse_stream(stream, filename=filename, species_map=species_map)
            canonical, issues = materialize(frame_stream)
            note = ParseIssue(
                severity="warning",
                code=_SPECIES_SUPPLIED,
                message=(
                    "element symbols supplied via recovery choice "
                    f"{choice!r} ({wording}); the source dump listed only numeric atom types"
                ),
            )
            return ParseResult(canonical=canonical, issues=[*issues, note])
        raise NotImplementedError(f"lammps_dump parse_recover does not handle hint {hint!r}")

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        unit_style: UnitStyle | None = None,
        species_map: Mapping[int, str] | list[str] | None = None,
    ) -> FrameStream:
        """Header-eager, snapshot-lazy dump parse (M12; Part 3 §2).

        The first snapshot's block header **and its data rows** are read eagerly — the
        per-atom carry columns (``custom_per_atom``, first dim N) and the species resolution
        both need frame 0's values, and both live in the header — then every later snapshot
        is read and yielded one at a time, so peak memory tracks one frame block.

        ``unit_style`` / ``species_map`` are the parse-time recovery inputs (reached through
        ``parse_recover``); the defaults honor the file's own declarations and refuse
        honestly when they are absent.
        """
        issues: list[ParseIssue] = []
        lines = _Lines(stream)
        first_line = lines.next()
        if first_line is None or first_line.strip() == "":
            raise _error(_EMPTY, "file is empty; a LAMMPS dump starts with 'ITEM: TIMESTEP'")

        lines.push(first_line.rstrip("\n"))
        first = _read_block_header(lines, unit_style=unit_style, frame_index=0)
        if first.unit_style is None:
            raise _error(
                _AMBIGUOUS_UNITS,
                "no unit style declared (no ITEM: UNITS header); every position, velocity, "
                "and box bound is uninterpretable until the style is known — refuse, never "
                "guess (R3)",
                location="frame 0",
                hint=_UNITS_HINT,
            )
        first_rows = _read_data_rows(lines, first)
        # Captured by the frame generator below: mypy cannot narrow a closure-captured
        # attribute across the refusal, so the non-None style is captured in a local.
        first_style = first.unit_style
        assert first_style is not None  # refused above; the generator relies on it
        first_declared = first.unit_declared
        first_frame, carries, symbols = _build_frame(
            first, first_rows, species_map=species_map, issues=issues, index=0
        )

        coordinate_kind = _coordinate_kind(first)
        parse_notes = [
            coordinate_note(coordinate_kind.kind),
            f"Unit style in force: {first.unit_style.code} ({first.unit_style.summary})"
            + (" — declared in the file." if first.unit_declared else " — applied by recovery."),
            f"pbc read from the dump's boundary flags: {first.pbc}.",
            "The dump declares step numbers, not a time axis (no timestep size in the file); "
            "trajectory.timestep stays None (P3) and each step rides in "
            f"user_metadata.custom_per_frame[{_STEP_KEY!r}].",
        ]
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={
                "positions": _units_distance(first.unit_style),
                "lattice_vectors": _units_distance(first.unit_style),
                "velocities": _units_velocity(first.unit_style),
            },
            parse_notes=parse_notes,
        )
        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=provenance,
            trajectory=TrajectoryMetadata(timestep=None),
            custom_per_atom=carries,
        )

        def _frames() -> Iterator[StreamFrame]:
            warned: set[str] = set()
            yield StreamFrame(frame=first_frame, per_frame_custom={_STEP_KEY: first.step})
            index = 1
            while True:
                boundary = lines.next_significant()
                if boundary is None:
                    return  # a complete file ends after a complete snapshot
                lines.push(boundary)
                header_k = _read_block_header(lines, unit_style=unit_style, frame_index=index)
                hk_style = header_k.unit_style
                if hk_style is None:
                    raise _error(
                        _MALFORMED,
                        f"frame {index} declares no unit style but frame 0 does; a dump's "
                        "unit declaration cannot appear mid-file",
                        location=f"frame {index}",
                    )
                if (header_k.unit_declared, hk_style.code) != (first_declared, first_style.code):
                    raise _error(
                        _MALFORMED,
                        f"frame {index} declares units {hk_style.code!r} but "
                        f"frame 0 declares {first_style.code!r}; a dump's unit style "
                        "must be constant across frames",
                        location=f"frame {index}",
                    )
                if header_k.columns != first.columns:
                    raise _error(
                        _MALFORMED,
                        f"frame {index} renames its per-atom columns to {header_k.columns}; "
                        "a dump's column layout must be constant across frames",
                        location=f"frame {index}",
                    )
                if header_k.n_atoms != first.n_atoms:
                    raise _error(
                        _VARIABLE_ATOM_COUNT,
                        f"frame {index} declares {header_k.n_atoms} atoms but frame 0 "
                        f"declares {first.n_atoms}; the canonical model requires a constant "
                        "atom count across frames (Part 2 §3.2). Per-frame counts seen: "
                        f"[{first.n_atoms}, {header_k.n_atoms}] — measured, never padded or "
                        "truncated",
                        location=f"frame {index}",
                    )
                rows = _read_data_rows(lines, header_k)
                frame_k, _, symbols_k = _build_frame(
                    header_k,
                    rows,
                    species_map=species_map,
                    issues=issues,
                    index=index,
                    first_carries=carries,
                    warned=warned,
                )
                if symbols_k != symbols:
                    raise _error(
                        _VARIABLE_SPECIES,
                        f"frame {index} resolves to species {symbols_k} but frame 0 resolves "
                        f"to {symbols}; the canonical model requires a constant atom "
                        "identity across frames (Part 2 §3.2)",
                        location=f"frame {index}",
                    )
                yield StreamFrame(frame=frame_k, per_frame_custom={_STEP_KEY: header_k.step})
                index += 1

        return FrameStream(header, _frames(), issues=issues)

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Element-labeled dumps read directly; numeric-type dumps resolve "
                        "through the missing_species recovery (species_map), never guessed."
                    ),
                ),
                "atoms.positions": full,
                "cell.lattice_vectors": full,
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="From the dump's boundary flags (p/f/s/m per direction).",
                ),
                "dynamics.velocities": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only when vx/vy/vz columns are present; unit-converted from the "
                    "style's velocity unit.",
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Arbitrary compute/fix output columns carried verbatim (frame 0).",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Per-snapshot step number."
                ),
            },
            max_frames=None,  # the point of the format: unbounded snapshot count
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="cartesian",
            lossy_notes=[],
            # The named image-flag capability dimension (M46-S3, D176): lammps_dump reads the
            # ix/iy/iz flags specifically (they survive into the canonical object), so the
            # pre-flight diff can predict the unwrapping loss when such a source targets a format
            # that cannot hold them. The incumbent formats declare absence by the default.
            holds_image_flags=True,
        )


# --- frame building ------------------------------------------------------------------


def _coordinate_kind(header: _BlockHeader) -> CoordinateColumns:
    """Resolve the coordinate family in force for ``header`` (S1's resolver)."""
    try:
        return resolve_coordinate_columns(header.columns)
    except ValueError as exc:
        raise _error(_MALFORMED, f"{header.location}: {exc}") from exc


def _build_frame(
    header: _BlockHeader,
    rows: list[list[str]],
    *,
    species_map: Mapping[int, str] | list[str] | None,
    issues: list[ParseIssue],
    index: int,
    first_carries: Mapping[str, object] | None = None,
    warned: set[str] | None = None,
) -> tuple[Frame, dict[str, object], list[str]]:
    """One snapshot → (Frame, per-atom carries, symbols).

    The carries are built for every snapshot (they are needed to compare later snapshots
    against frame 0), but only frame 0's become the object-level ``custom_per_atom``; the
    caller passes them in as ``first_carries`` for later snapshots so a column whose values
    vary across frames warns once per column (``custom_per_atom`` is stored once per object,
    Part 2 §3.10 — the extXYZ streaming consistency check, same shape).
    """
    assert header.unit_style is not None  # refused in parse_stream before any frame is built
    style = header.unit_style
    distance = style.distance_to_angstrom

    coords = _coordinate_kind(header)
    positions_raw: np.ndarray
    if coords.kind.value == "scaled":
        scaled = np.column_stack(
            [_column_floats(rows, _column_index(header, name), header) for name in coords.columns]
        )
        positions_raw = scaled_to_cartesian(scaled, header.box)
    else:
        positions_raw = np.column_stack(
            [_column_floats(rows, _column_index(header, name), header) for name in coords.columns]
        )
        positions_raw = positions_raw - header.box.origin
    positions = positions_raw * distance

    symbols = _resolve_symbols(header, rows, species_map)

    velocities: np.ndarray | None = None
    if all(name in header.columns for name in _VELOCITY_COLUMNS):
        velocities = (
            np.column_stack(
                [
                    _column_floats(rows, _column_index(header, name), header)
                    for name in _VELOCITY_COLUMNS
                ]
            )
            * style.velocity_to_angstrom_per_femtosecond
        )
    elif any(name in header.columns for name in _VELOCITY_COLUMNS):
        raise _error(
            _MALFORMED,
            f"{header.location} declares a partial velocity family; vx/vy/vz must come "
            "together or not at all",
            location=header.location,
        )

    carries: dict[str, object] = {}
    if "type" in header.columns:
        carries[_TYPE_KEY] = _column_floats(rows, _column_index(header, "type"), header)
    if "id" in header.columns:
        carries[_ID_KEY] = _column_floats(rows, _column_index(header, "id"), header)

    # The specific image-flag carry (M46-S3): a complete ix/iy/iz family is a named structured
    # payload — never the generic unmapped-column path — because a wrapped dump plus its flags
    # contains everything needed to reconstruct continuous trajectories, and dropping them makes
    # unwrapping impossible while the output looks correct. The coordinate convention in force is
    # stated *alongside* the warning (the two facts are only useful together), and the flags are
    # never applied on parse (D43). A partial family is malformed, refused — never guessed.
    image_flags_present = [name for name in _IMAGE_FLAG_COLUMNS if name in header.columns]
    if len(image_flags_present) == 3:
        flags = np.column_stack(
            [
                _column_floats(rows, _column_index(header, name), header)
                for name in _IMAGE_FLAG_COLUMNS
            ]
        )
        carries[IMAGE_FLAGS_CARRY_KEY] = flags
        if first_carries is None:
            convention = {
                "cartesian": "wrapped Cartesian (x/y/z)",
                "scaled": "scaled (xs/ys/zs)",
                "unwrapped": "unwrapped Cartesian (xu/yu/zu)",
            }[coords.kind.value]
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=_IMAGE_FLAGS_CARRIED,
                    message=(
                        f"per-atom image flags (ix/iy/iz) carried to "
                        f"user_metadata.custom_per_atom[{IMAGE_FLAGS_CARRY_KEY!r}]; coordinates "
                        f"are {convention}, so unwrapping remains possible from a format that can "
                        "hold them. The flags are never applied on parse (D43)."
                    ),
                    location="frame 0",
                )
            )
    elif image_flags_present:
        raise _error(
            _MALFORMED,
            f"{header.location} declares a partial image-flag family; ix/iy/iz must come "
            "together or not at all",
            location=header.location,
        )

    for name in header.columns:
        if name in _KNOWN_COLUMNS or is_element_column(name) or name in _IMAGE_FLAG_COLUMNS:
            continue
        values = _column_floats(rows, _column_index(header, name), header)
        carries[f"{_CUSTOM_PREFIX}{name}"] = values
        if first_carries is None:
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=_UNMAPPED_CARRIED,
                    message=(
                        f"per-atom column {name!r} has no canonical field; carried verbatim in "
                        f"user_metadata.custom_per_atom['{_CUSTOM_PREFIX}{name}'] (frame 0)"
                    ),
                    location="frame 0",
                )
            )

    if first_carries is not None and warned is not None:
        for carry_key, carry_values in carries.items():
            if carry_key not in first_carries or not np.array_equal(
                np.asarray(carry_values), np.asarray(first_carries[carry_key])
            ):
                if carry_key not in warned:
                    warned.add(carry_key)
                    issues.append(
                        ParseIssue(
                            severity="warning",
                            code=_PER_FRAME_COLUMN,
                            message=(
                                f"per-atom column {carry_key!r} varies across frames; the "
                                "canonical model stores per-atom custom arrays once per object "
                                "(Part 2 §3.10), so only frame 0's values are carried"
                            ),
                            location=f"frame {index}",
                        )
                    )

    frame = Frame(
        index=index,
        atoms=AtomsBlock(symbols=symbols, positions=positions),
        cell=Cell(lattice_vectors=header.box.lattice * distance, pbc=header.pbc),
        dynamics=Dynamics(velocities=velocities),
    )
    return frame, carries, symbols


def _resolve_symbols(
    header: _BlockHeader,
    rows: list[list[str]],
    species_map: Mapping[int, str] | list[str] | None,
) -> list[str]:
    """The frame's element symbols: an element column resolves directly; a numeric type
    column resolves only under a ``species_map`` preset (the existing ``missing_species``
    case, Part 3 §7.2) and refuses recoverably otherwise."""
    element_names = [name for name in header.columns if is_element_column(name)]
    if len(element_names) > 1:
        raise _error(
            _MALFORMED,
            f"{header.location} declares more than one element column ({element_names}); the "
            "species source is ambiguous",
            location=header.location,
        )
    if element_names:
        column = _column_strings(rows, _column_index(header, element_names[0]))
        try:
            return resolve_species(type_values=None, element_column=column, species_map=None)
        except ValueError as exc:
            raise _error(_MALFORMED, f"{header.location}: {exc}") from exc
    if "type" not in header.columns:
        raise _error(
            _NO_SPECIES_COLUMN,
            f"{header.location} carries neither an element column nor a numeric type column; "
            "the atom species cannot be determined (Part 2 §3.3)",
            location=header.location,
        )
    if species_map is None:
        raise _error(
            _MISSING_SPECIES,
            f"{header.location} lists numeric atom types but no species_map preset was "
            "supplied; symbols are required and did not exist in the file (Part 2 §3.3)",
            location=header.location,
            hint=_SPECIES_HINT,
        )
    types = _column_floats(rows, _column_index(header, "type"), header)
    # LAMMPS types are 1-based integers; a non-integral value is a malformed file, never
    # something to round silently (P1 — a guessed type would fabricate a species identity).
    if not np.all(types == np.floor(types)):
        raise _error(
            _MALFORMED,
            f"{header.location} type column holds non-integer values; LAMMPS atom types are "
            "1-based integers",
            location=header.location,
        )
    int_types = types.astype(np.int64)
    try:
        return resolve_species(type_values=int_types, element_column=None, species_map=species_map)
    except ValueError as exc:
        raise _error(_MALFORMED, f"{header.location}: {exc}") from exc


def _recover_species_map(parameters: dict[str, object]) -> Mapping[int, str] | list[str]:
    """Parse the ``species_map`` choice's ``species`` parameter (Part 4 §3.3): a dict or
    ordered list passes through; the CLI's string form (``"1:Si 2:O"`` — colon-delimited
    type:symbol pairs, space-separated, since commas are the ``--recover`` separator) is split
    into a type→symbol mapping. Commas inside the string are tolerated too, so a direct API
    caller can pass ``"1:Si,2:O"``."""
    raw = parameters.get("species")
    if isinstance(raw, dict):
        return {int(k): str(v) for k, v in raw.items()}
    if isinstance(raw, (list, tuple)):
        return [str(s) for s in raw]
    if isinstance(raw, str):
        tokens = raw.replace(":", " ").replace(",", " ").split()
        if len(tokens) == 0 or len(tokens) % 2 != 0:
            raise _error(
                _MISSING_SPECIES,
                f"species_map needs type:symbol pairs (e.g. species='1:Si 2:O'), got {raw!r}",
                hint=_SPECIES_HINT,
            )
        mapping: dict[int, str] = {}
        for i in range(0, len(tokens), 2):
            try:
                key = int(tokens[i])
            except ValueError:
                raise _error(
                    _MISSING_SPECIES,
                    f"species_map type {tokens[i]!r} is not an integer atom type",
                    hint=_SPECIES_HINT,
                ) from None
            mapping[key] = tokens[i + 1]
        return mapping
    raise _error(
        _MISSING_SPECIES,
        "species_map needs a 'species' parameter (a type→symbol map, an ordered symbol "
        "list, or '1:Si 2:O')",
        hint=_SPECIES_HINT,
    )


def _reference_species_map(parameters: dict[str, object]) -> Mapping[int, str]:
    """Build the type→symbol map for the ``upload_reference`` choice from a matching
    reference structure (Part 4 §3.3): the CLI injects a parsed ``reference`` CanonicalObject
    (``cli._inject_references``); its frame-0 per-atom symbols, indexed by atom, become the
    map. A count mismatch is caught by the shared core's two-sided validation — every
    observed type must be named and every map entry must be observed — so a reference that
    does not match this dump is refused, never silently trimmed."""
    ref = parameters.get("reference")
    if ref is None:
        raise _error(
            _MISSING_SPECIES,
            "upload_reference needs a 'reference' parameter (the parsed reference structure); "
            "pass --recover missing_species=upload_reference,file=PATH",
            hint=_SPECIES_HINT,
        )
    reference = cast(CanonicalObject, ref)
    symbols = reference.frames[0].atoms.symbols
    return {i + 1: str(s) for i, s in enumerate(symbols)}


def _units_distance(style: UnitStyle) -> str:
    return {"metal": "angstrom", "real": "angstrom", "si": "meter"}[style.code]


def _units_velocity(style: UnitStyle) -> str:
    return {"metal": "angstrom/picosecond", "real": "angstrom/femtosecond", "si": "meter/second"}[
        style.code
    ]


def make_lammps_dump_parser() -> LammpsDumpParser:
    return LammpsDumpParser()
