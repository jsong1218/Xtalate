"""VASP OUTCAR parser (MASTER_SPEC Part 3 §3; v1.2 M43-S1).

The second **parser-only** format (S1's seam, D159): VASP's per-run log. OUTCAR is a *log, not a
format* — its layout drifts across VASP versions, so the reader does the log-line work
(anchor-string block scanning) and hands the M42 shared VASP core (``parsers._vasp``, D160) the
parsed numbers. Only the *scraping* is new: positions/cell/energy/force/stress mappings are reused
verbatim, so two parsers reading one run (OUTCAR + vasprun.xml) cannot co-discover divergent
mappings (standing rule 4).

**Streaming-first.** ``parse_stream`` is the real implementation and ``parse`` is defined as
``materialize(parse_stream(...))`` (the D56 one-code-path rule, as vasprun/xdatcar), so whole-file
and streamed readings cannot diverge. The log is read line by line off the byte stream; the header
is parsed eagerly and each ionic step is yielded lazily, so peak memory tracks the resident step,
not the file — the property M44 will measure at 10⁴ steps.

**Format facts handled at parse time and recorded, never guessed (Part 3 §5 rule 3):**

* **The frame is keyed on the ``POSITION … TOTAL-FORCE`` table** — one per ionic step, never in the
  header. Within a step (the canonical VASP 5.x/6.x order) the ``energy(sigma->0)`` line is followed
  by the ``in kB`` stress line and then the table, so the energy/stress seen before a table belong
  to that table's step (buffered in a ``_Pending`` until the table completes). A table with no
  preceding ``energy(sigma->0)`` line is a ``ParseError`` (P3 — never a defaulted energy).
* **Positions are Cartesian (Å)** — read from the ``POSITION … TOTAL-FORCE`` table columns as-is
  (``mode=\"cartesian\"``), never re-run through the fractional→Cartesian lattice multiply.
  vasprun.xml positions are direct (fractional); the two readers land the same Cartesian positions
  (the M43 cross-check pins it).
* **Energy** — ``electronic.total_energy`` maps ``energy(sigma->0)`` (VASP's energy extrapolated to
  zero smearing, the same physical quantity as vasprun.xml's ``e_0_energy`` — the core's
  ``TOTAL_ENERGY_TAG`` decision). The ``energy without entropy`` scalar on the same line is carried
  verbatim per frame (never dropped, **P1**; never substituted for the total energy).
* **Per-step cells (NpT).** A step's own ``direct lattice vectors`` block (when present) supplies
  that step's cell; a step without one reuses the running cell — the fixed-cell form (vasprun's
  ``_StepState`` pattern).
* **``pbc = (T,T,T)``** by format definition, as a ``parse_notes`` entry.

**Error contract (Part 3 §5; the base ``OUTCAR_*`` code set of D164).** ``OUTCAR_EMPTY`` (empty
file or no ionic-step block at all), ``OUTCAR_MISSING_BLOCK`` (an expected block — the version
banner, the species list, the initial lattice, the ``energy(sigma->0)`` line, the force table — is
absent in an otherwise-recognized context: a ``ParseError``, never a defaulted field, P3), and the
warning ``OUTCAR_UNMAPPED_LINE_CARRIED`` (a recognized-but-unmapped diagnostic scalar carried
verbatim, P1). ``OUTCAR_UNRECOGNIZED_LAYOUT`` / ``OUTCAR_INCONSISTENT_STEP`` land in S2 (the
version-drift refusal discipline) and ``OUTCAR_TRUNCATED`` in S3 (truncation recovery) — the codes
exist where the behaviour lands, not all at once.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

from xtalate.parsers._common import build_provenance
from xtalate.parsers._vasp import (
    build_cell,
    forces,
    positions,
    stress_from_vasp_kbar,
    stress_voigt6_vasp_to_full,
    symbols_from_symbol_counts,
    total_energy,
)
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    Dynamics,
    Electronic,
    Frame,
    SimulationMetadata,
    TrajectoryMetadata,
)
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    FrameStream,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
    StreamFrame,
    StreamHeader,
    materialize,
)

FORMAT_ID = "outcar"
# The conventional VASP filename — a sniffing fact, like POSCAR/XDATCAR; the *format id* is the bare
# lowercase token used in `--format`/`--to` and provenance.source_format (D160).
CONVENTIONAL_NAME = "OUTCAR"

_CARRY_KEY_PREFIX = "outcar:"
_ENERGY_WO_ENTROPY_KEY = "energy_without_entropy"

# A single float token, including VASP's exponent forms (-0.12345678E+02).
_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

#: The version banner (` vasp.6.3.2 08Feb23 (build …)`) — the first such line is the declared
#: program.
_VERSION_RE = re.compile(r"\bvasp\.\d+\.\d+")
#: POTCAR species symbols, from `VRHFIN =X:` (one per species, in declared order). The bare element
#: symbol is the reliable source — the POTCAR `TITEL`/`POTCAR:` titles can carry `_pv`/`_sv`
#: suffixes.
_VRHFIN_RE = re.compile(r"VRHFIN\s*=\s*([A-Za-z]{1,2})\s*:")
_IONS_PER_TYPE_RE = re.compile(r"ions\s+per\s+type\s*=\s*(.*)")
_NIONS_RE = re.compile(r"NIONS\s*=\s*(\d+)")
_SIGMA0_RE = re.compile(rf"energy\(sigma->0\)\s*=\s*({_FLOAT})")
_WO_ENTROPY_RE = re.compile(rf"energy\s+without\s+entropy\s*=\s*({_FLOAT})")
_STRESS_RE = re.compile(r"\bin\s+kB\b\s+(.*)")
#: A table frame — a run of only whitespace and dashes (``-----…``), which VASP draws around its
#: tabular blocks (the POSITION/TOTAL-FORCE table is framed by two).
_SEPARATOR_RE = re.compile(r"^[\s-]*$")

_POSITIONS_NOTE = (
    "Cartesian positions (angstrom) read as-is from the POSITION … TOTAL-FORCE table "
    "(OUTCAR writes Cartesian, unlike vasprun.xml's direct coordinates)."
)
_PBC_NOTE = (
    "pbc set to (true,true,true): OUTCAR carries no PBC declaration and VASP is always fully "
    "periodic (format-defined, not assumed)."
)
_ENERGY_NOTE = (
    "electronic.total_energy read from energy(sigma->0) — VASP's energy extrapolated to zero "
    "smearing (the e_0_energy of vasprun.xml); the energy-without-entropy scalar is carried "
    "verbatim in user_metadata.custom_per_frame['outcar:energy_without_entropy']."
)
_SOURCE_CODE_NOTE = "simulation.source_code set to the VASP version banner (verbatim)."
_CELL_NOTE = "cell.lattice_vectors assembled from the direct lattice vectors block (rows a, b, c)."
_STEP_CELL_NOTE = (
    "Each ionic step's own direct lattice vectors block (when present) supplies that step's cell; "
    "a step without one reuses the running cell (the fixed-cell form)."
)
_STRESS_NOTE = (
    "electronic.stress mapped from the 'in kB' Voigt-6 stress line: VASP reports pressure "
    "(compression-positive) in kBar, so the tensor is sign-flipped to canonical tension-positive "
    "and divided by the exact factor 1602.1766208 kBar per eV/Å³ (D161). The 'in kB' line carries "
    'the same sign as vasprun.xml\'s <varray name="stress"> (pinned by the OUTCAR↔vasprun '
    "cross-check), so no additional sign correction is applied. A step without a stress line "
    "leaves electronic.stress None (P3 — absence is never defaulted)."
)

_PARSE_NOTES = [
    _POSITIONS_NOTE,
    _PBC_NOTE,
    _ENERGY_NOTE,
    _SOURCE_CODE_NOTE,
    _CELL_NOTE,
    _STEP_CELL_NOTE,
    _STRESS_NOTE,
]


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


def _carry_warning(key: str, *, location: str) -> ParseIssue:
    return ParseIssue(
        severity="warning",
        code="OUTCAR_UNMAPPED_LINE_CARRIED",
        message=(
            f"the '{key}' diagnostic has no canonical field; carried verbatim in "
            f"user_metadata.custom_per_frame['{_CARRY_KEY_PREFIX}{key}']"
        ),
        location=location,
    )


def _line_reader(stream: BinaryIO) -> Iterator[str]:
    """Yield decoded lines off the raw byte stream one at a time.

    Line-at-a-time (rather than ``stream.read()``) is what keeps the streaming parser's peak memory
    bounded by a step instead of the file. A non-UTF-8 byte raises the structured ``ParseError`` of
    Part 3 §5 at the point of failure — the shared text-format encoding-error contract
    (``_common.decode_text`` / XDATCAR's ``XDATCAR_ENCODING_ERROR``).
    """
    while True:
        raw = stream.readline()
        if raw == b"":
            return
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                "OUTCAR_ENCODING_ERROR",
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); outcar is a text "
                "format",
            ) from exc


def _species_from_vrhfin(line: str) -> str | None:
    match = _VRHFIN_RE.search(line)
    return match.group(1) if match else None


def _parse_counts(line: str) -> list[int] | None:
    match = _IONS_PER_TYPE_RE.search(line)
    if match is None:
        return None
    counts: list[int] = []
    for token in match.group(1).split():
        try:
            counts.append(int(token))
        except ValueError:
            return None
    return counts


def _parse_nions(line: str) -> int | None:
    match = _NIONS_RE.search(line)
    return int(match.group(1)) if match else None


def _read_lattice(lines: Iterator[str], *, where: str) -> np.ndarray:
    """The 3×3 lattice from the three rows after a ``direct lattice vectors`` header line.

    VASP prints each row as 6 numbers — the direct vectors followed by the reciprocal ones — so the
    first three columns are the lattice rows a, b, c.
    """
    rows: list[list[float]] = []
    for _k in range(3):
        line = next(lines, None)
        if line is None:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"file ended inside the direct lattice vectors block ({where})",
                location=where,
            )
        parts = line.split()
        if len(parts) < 6:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"lattice row has fewer than 6 components ({where}): {line.strip()!r}",
                location=where,
            )
        try:
            rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
        except ValueError as exc:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"non-numeric lattice row ({where}): {line.strip()!r}",
                location=where,
            ) from exc
    return np.asarray(rows, dtype=float)


@dataclass
class _Header:
    """Everything parsed eagerly before the first ionic step: the declared program, the per-atom
    symbols (hence the atom count), and the initial lattice that fixed-cell steps reuse."""

    version: str | None
    symbols: list[str]
    n_atoms: int
    lattice: np.ndarray


def _finalize_header(
    version: str | None,
    species: list[str],
    counts: list[int] | None,
    nions: int | None,
    lattice: np.ndarray | None,
) -> _Header:
    """Validate the eagerly-scanned header and build the ``_Header``.

    A missing expected header block — no version banner, no species list, no initial lattice — is a
    ``ParseError`` under the §5 contract, never a defaulted field (P3). ``NIONS`` is a cross-check
    against the species counts, not the source of the count (the symbols come from the declared
    species, so the count must match them).
    """
    if version is None:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            "no VASP version banner (vasp.<major>.<minor>) found before the first ionic step",
        )
    if not species or counts is None or len(species) != len(counts):
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            "no ion species found (a VRHFIN =X: line per species and an 'ions per type' line are "
            "required)",
        )
    n_atoms = sum(counts)
    if n_atoms == 0:
        raise _error("OUTCAR_MISSING_BLOCK", "header declares zero ions")
    if nions is not None and nions != n_atoms:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            f"header declares NIONS = {nions} but 'ions per type' sums to {n_atoms}",
        )
    try:
        symbols = symbols_from_symbol_counts(list(zip(species, counts, strict=True)))
    except KeyError as exc:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            f"header declares an element symbol not in the element table: {exc}",
        ) from exc
    if lattice is None:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            "no direct lattice vectors block found in the header",
        )
    return _Header(version=version, symbols=symbols, n_atoms=n_atoms, lattice=lattice)


@dataclass
class _Pending:
    """The step fields seen so far for the next frame. Energy is required (P3); stress optional."""

    energy: float | None
    carry: float | None
    stress: np.ndarray | None


def _read_header(lines: Iterator[str]) -> tuple[_Header | None, _Pending | None]:
    """Scan the header eagerly and stop at the first ``POSITION … TOTAL-FORCE`` header line.

    Returns ``(None, None)`` when the file ends with no ionic-step table (the caller raises
    ``OUTCAR_EMPTY``). The first step's ``energy(sigma->0)`` and ``in kB`` lines appear *before*
    its table (the canonical VASP order), so they are captured into the returned ``_Pending`` for
    the step loop — one pass, no re-reading.
    """
    version: str | None = None
    species: list[str] = []
    counts: list[int] | None = None
    nions: int | None = None
    lattice: np.ndarray | None = None
    pending_energy: float | None = None
    pending_carry: float | None = None
    pending_stress: np.ndarray | None = None
    for line in lines:
        if "TOTAL-FORCE" in line:
            header = _finalize_header(version, species, counts, nions, lattice)
            return header, _Pending(pending_energy, pending_carry, pending_stress)
        if version is None and "vasp." in line:
            if _VERSION_RE.search(line):
                version = line.strip()
        if "VRHFIN" in line:
            symbol = _species_from_vrhfin(line)
            if symbol is not None:
                species.append(symbol)
        if "ions per type" in line:
            parsed = _parse_counts(line)
            if parsed is not None:
                counts = parsed
        if nions is None and "NIONS" in line:
            nions = _parse_nions(line)
        if "direct lattice vectors" in line:
            lattice = _read_lattice(lines, where="header")
        elif "energy(sigma->0)" in line:
            pending_energy, pending_carry = _parse_energy_line(line, 0)
        elif "in kB" in line:
            pending_stress = _parse_stress(line, 0)
    if pending_energy is not None or pending_stress is not None:
        # A step began (its energy/stress lines) but no POSITION/TOTAL-FORCE table followed — a torn
        # write, never a silently empty parse (S3 refines this into OUTCAR_TRUNCATED + recovery).
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            "file ends mid-step (a torn write) with an energy/stress line but no "
            "POSITION/TOTAL-FORCE table (P3: never a partial frame)",
            location="frame 0",
        )
    return None, None


def _parse_energy_line(line: str, frame_index: int) -> tuple[float, float | None]:
    """The step's ``energy(sigma->0)`` total energy plus the ``energy without entropy`` carry.

    Both scalars live on the one line; the total energy maps to ``electronic.total_energy`` and the
    other scalar is carried verbatim (it is VASP's TOTEN-adjacent value, never substituted for the
    total energy — P1).
    """
    match = _SIGMA0_RE.search(line)
    if match is None:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            f"ionic step {frame_index}: the energy(sigma->0) line has no parseable value: "
            f"{line.strip()!r}",
            location=f"frame {frame_index}",
        )
    sigma0 = float(match.group(1))
    carry_match = _WO_ENTROPY_RE.search(line)
    carry = float(carry_match.group(1)) if carry_match else None
    return sigma0, carry


def _parse_stress(line: str, frame_index: int) -> np.ndarray:
    """The step's ``electronic.stress`` from the ``in kB`` Voigt-6 line, mapped through the core.

    The line carries 6 components in VASP Voigt order ``[XX, YY, ZZ, XY, YZ, ZX]``, kBar,
    compression-positive — the same sign as vasprun.xml's stress varray (D161; pinned by the
    cross-check) — so the shared ``stress_from_vasp_kbar(stress_voigt6_vasp_to_full(...))`` mapping
    applies with no additional sign correction.
    """
    match = _STRESS_RE.search(line)
    if match is None:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            f"ionic step {frame_index}: the 'in kB' stress line has no parseable value: "
            f"{line.strip()!r}",
            location=f"frame {frame_index}",
        )
    tokens = match.group(1).split()
    if len(tokens) < 6:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            f"ionic step {frame_index}: the 'in kB' stress line has fewer than 6 components: "
            f"{line.strip()!r}",
            location=f"frame {frame_index}",
        )
    try:
        voigt6 = [float(tokens[i]) for i in range(6)]
    except ValueError as exc:
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            f"ionic step {frame_index}: non-numeric 'in kB' stress line: {line.strip()!r}",
            location=f"frame {frame_index}",
        ) from exc
    return stress_from_vasp_kbar(stress_voigt6_vasp_to_full(voigt6))


def _next_data_line(lines: Iterator[str]) -> str | None:
    """The next non-blank, non-dash-separator line — VASP frames its tables with ``---…`` rules."""
    for line in lines:
        if line.strip() and not _SEPARATOR_RE.match(line):
            return line
    return None


def _read_force_rows(lines: Iterator[str], n_atoms: int, frame_index: int) -> np.ndarray:
    """The ``n_atoms`` rows of the ``POSITION … TOTAL-FORCE`` table (``x y z fx fy fz``).

    A block that ends before its rows complete, or a row that is not 6 numeric components, is a
    ``ParseError`` — never a silently shortened table (P2) and never a defaulted force (P3).
    """
    rows: list[list[float]] = []
    for a in range(n_atoms):
        line = _next_data_line(lines)
        if line is None:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"ionic step {frame_index}: the POSITION/TOTAL-FORCE table ended after {a} of "
                f"{n_atoms} atoms",
                location=f"frame {frame_index}",
            )
        parts = line.split()
        if len(parts) != 6:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"ionic step {frame_index}: force row {a + 1} has {len(parts)} components, "
                f"expected 6 (x y z fx fy fz): {line.strip()!r}",
                location=f"frame {frame_index}",
            )
        try:
            rows.append([float(p) for p in parts])
        except ValueError as exc:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"ionic step {frame_index}: non-numeric force row: {line.strip()!r}",
                location=f"frame {frame_index}",
            ) from exc
    return np.asarray(rows, dtype=float)


def _build_frame(
    header: _Header,
    rows: np.ndarray,
    lattice: np.ndarray,
    energy: float,
    carry: float | None,
    stress: np.ndarray | None,
    issues: list[ParseIssue],
    frame_index: int,
) -> StreamFrame:
    """Build one frame from the parsed force rows and the step's pending energy/stress."""
    frame = Frame(
        index=frame_index,
        atoms=AtomsBlock(
            symbols=list(header.symbols),
            positions=positions(rows[:, :3], lattice, mode="cartesian"),
        ),
        cell=build_cell(lattice),
        dynamics=Dynamics(forces=forces(rows[:, 3:])),
        electronic=Electronic(total_energy=total_energy(energy), stress=stress),
    )
    per_frame_custom: dict[str, object] = {}
    if carry is not None:
        key = f"{_CARRY_KEY_PREFIX}{_ENERGY_WO_ENTROPY_KEY}"
        per_frame_custom[key] = carry
        issues.append(_carry_warning(_ENERGY_WO_ENTROPY_KEY, location=f"frame {frame_index}"))
    return StreamFrame(frame=frame, per_frame_custom=per_frame_custom)


def _scan_to_next_frame(
    lines: Iterator[str], lattice: np.ndarray, frame_index: int
) -> tuple[_Pending, np.ndarray, bool]:
    """Scan forward for the next ``POSITION … TOTAL-FORCE`` header, accumulating that step's
    energy/stress/own-cell along the way.

    Returns ``(pending, lattice, found)``. Reaching end-of-file *after* a step began (an energy or
    stress line with no table) is a torn write — a ``ParseError``, never a silently dropped partial
    step (S3 refines this into ``OUTCAR_TRUNCATED`` + truncation recovery).
    """
    pending_energy: float | None = None
    pending_carry: float | None = None
    pending_stress: np.ndarray | None = None
    saw_step = False
    while True:
        line = next(lines, None)
        if line is None:
            if saw_step:
                raise _error(
                    "OUTCAR_MISSING_BLOCK",
                    f"ionic step {frame_index}: file ends mid-step after its energy/stress lines "
                    "(a torn write) with no POSITION/TOTAL-FORCE table (P3: never a partial frame)",
                    location=f"frame {frame_index}",
                )
            return _Pending(None, None, None), lattice, False
        if "TOTAL-FORCE" in line:
            return _Pending(pending_energy, pending_carry, pending_stress), lattice, True
        if "energy(sigma->0)" in line:
            pending_energy, pending_carry = _parse_energy_line(line, frame_index)
            saw_step = True
        elif "in kB" in line:
            pending_stress = _parse_stress(line, frame_index)
            saw_step = True
        elif "direct lattice vectors" in line:
            lattice = _read_lattice(lines, where=f"frame {frame_index}")
            saw_step = True


def _steps(
    lines: Iterator[str],
    header: _Header,
    first_pending: _Pending,
    issues: list[ParseIssue],
) -> Iterator[StreamFrame]:
    """Yield one ``StreamFrame`` per ``POSITION … TOTAL-FORCE`` table, lazily, one step resident."""
    lattice = header.lattice
    pending = first_pending
    frame_index = 0
    while True:
        rows = _read_force_rows(lines, header.n_atoms, frame_index)
        energy = pending.energy
        if energy is None:
            raise _error(
                "OUTCAR_MISSING_BLOCK",
                f"ionic step {frame_index}: no energy(sigma->0) line before its "
                "POSITION/TOTAL-FORCE table (P3: never a defaulted energy)",
                location=f"frame {frame_index}",
            )
        yield _build_frame(
            header, rows, lattice, energy, pending.carry, pending.stress, issues, frame_index
        )
        frame_index += 1
        pending, lattice, found = _scan_to_next_frame(lines, lattice, frame_index)
        if not found:
            return


class OutcarParser(ParserPlugin):
    """VASP OUTCAR reader (Part 3 §3; v1.2 M43-S1). Parser-only (D159)."""

    format_id = FORMAT_ID
    format_name = "VASP OUTCAR"
    version = "0.1.0"
    file_extensions = ()  # OUTCAR is a conventional *name*, not an extension.

    def sniff(self, head: bytes, filename: str | None) -> float:
        # VASP's exact conventional filename selects this reading (§6.1), like POSCAR/XDATCAR; an
        # OUTCAR-prefixed name (e.g. `OUTCAR.relax`) is a strong-but-lenient hint.
        if filename is not None:
            if filename == CONVENTIONAL_NAME:
                return 1.0
            if filename.startswith(CONVENTIONAL_NAME):
                return 0.9
        # Content: the `vasp.<major>.<minor>` version banner near the top, or the characteristic
        # POSITION/TOTAL-FORCE + direct-lattice-vectors strings together.
        text = head.decode("utf-8", errors="replace")
        if _VERSION_RE.search(text):
            return 0.9
        if "TOTAL-FORCE" in text and "direct lattice vectors" in text:
            return 0.8
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56) — the streamed
        and whole-file readings are one code path and cannot diverge."""
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(self, stream: BinaryIO, *, filename: str | None) -> FrameStream:
        """Header-eager, step-lazy OUTCAR parse (M43-S1; Part 3 §2)."""
        head = stream.read(4096)
        if not head.strip():
            raise _error("OUTCAR_EMPTY", "file is empty")
        stream.seek(0)
        lines = _line_reader(stream)
        issues: list[ParseIssue] = []
        header, first_pending = _read_header(lines)
        if header is None or first_pending is None:
            raise _error(
                "OUTCAR_EMPTY",
                "file contains no ionic-step block (no POSITION/TOTAL-FORCE table)",
            )
        stream_header = _build_stream_header(header, filename)
        return FrameStream(
            stream_header, _steps(lines, header, first_pending, issues), issues=issues
        )

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        partial = CapabilityLevel.PARTIAL
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": FieldCapability(
                    level=full.level,
                    notes="Cartesian (Å), read as-is from the POSITION … TOTAL-FORCE table "
                    "(OUTCAR writes Cartesian, unlike vasprun.xml's direct coordinates).",
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=full.level,
                    notes="Per-ionic-step cells are read from each step's own direct lattice "
                    "vectors block (the NpT form); a step without one reuses the running cell "
                    "(the fixed-cell form).",
                ),
                "cell.pbc": FieldCapability(
                    level=partial,
                    notes="Always (T,T,T) by format definition; OUTCAR carries no explicit PBC.",
                ),
                "dynamics.forces": full,
                "electronic.total_energy": FieldCapability(
                    level=full.level,
                    notes="energy(sigma->0) — VASP's energy extrapolated to zero smearing "
                    "(the e_0_energy of vasprun.xml).",
                ),
                "electronic.stress": FieldCapability(
                    level=full.level,
                    notes="Deterministic mapping (D161): the 'in kB' Voigt-6 line (VASP order "
                    "[XX, YY, ZZ, XY, YZ, ZX], kBar, compression-positive — the same sign as "
                    "vasprun.xml's stress varray) is sign-flipped to canonical tension-positive "
                    "and divided by the exact factor 1602.1766208 kBar per eV/Å³; recorded in "
                    "parse_notes. A step without a stress line reads None (P3 — never a "
                    "defaulted zero tensor).",
                ),
                "simulation.extra": FieldCapability(
                    level=partial,
                    notes="Declared program string (the version banner) → simulation.source_code.",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=partial,
                    notes="Unmapped diagnostic scalars (energy without entropy) carried as "
                    "'outcar:<name>'.",
                ),
            },
            max_frames=None,  # a trajectory: unbounded step count
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )


def _build_stream_header(header: _Header, filename: str | None) -> StreamHeader:
    """Assemble the object-level metadata from the eagerly-parsed header."""
    return StreamHeader(
        schema_version=SCHEMA_VERSION,
        provenance=build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={
                "positions": "angstrom",
                "lattice_vectors": "angstrom",
                "stress": "kbar",
            },
            parse_notes=list(_PARSE_NOTES),
        ),
        # OUTCAR numbers its steps but declares no per-step time axis: absent, not invented (P3).
        trajectory=TrajectoryMetadata(timestep=None),
        simulation=SimulationMetadata(source_code=header.version, extra={}),
        custom_global={},
    )


def make_outcar_parser() -> OutcarParser:
    return OutcarParser()
