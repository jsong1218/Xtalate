"""Quantum ESPRESSO pw.x output parser (MASTER_SPEC Part 3 §3; v1.4 M52-S1).

The third **parser-only** format (the D159 seam; D195): the log a pw.x run prints. pw.x output
is a *log, not a format* — its layout drifts across QE 6.x/7.x — so the reader does the
log-line work (anchor-string block scanning) and hands the shared ``_qe`` core the parsed
numbers. Only the *scraping* is new: the structural understanding of a QE calculation is
pinned by the M50 input parser (``qe_pw_in``), which M52 reuses as ground truth — two parsers
reading one run cannot co-discover divergent mappings (standing rule 4), and the output
parser's setup-echo structure (cell / species / positions) must agree with the input parser's
parse of the corresponding input (the input-echo cross-check, this milestone's central
correctness proof).

**Streaming-first.** ``parse_stream`` is the real implementation and ``parse`` is defined as
``materialize(parse_stream(...))`` (the D56 one-code-path rule, as outcar/vasprun/xdatcar),
so whole-file and streamed readings cannot diverge. The log is read line by line off the byte
stream; the header is parsed eagerly and each ionic step is yielded lazily, so peak memory
tracks the resident step, not the file.

**Format facts handled at parse time and recorded, never guessed (Part 3 §5 rule 3):**

* **The frame is keyed on the ``!    total energy`` line** — one per ionic step (and one for
  an SCF-only run), printed after that step's SCF converges and *before* its force block. The
  per-step blocks (``Forces acting on atoms``, ``total   stress``, ``ATOMIC_POSITIONS``, and
  for ``vc-relax``/``vc-md`` an updated ``CELL_PARAMETERS``) are read in the window between one
  energy line and the next, so each frame carries its own step's labels; a step with no force
  block leaves ``dynamics.forces = None`` and one with no stress block leaves
  ``electronic.stress = None`` (**P3** — absence is never defaulted).
* **Positions: the declared per-block unit is read, never assumed.** QE labels each positions
  block's unit — the header's site table declares ``positions (<unit> units)`` and each
  per-step ``ATOMIC_POSITIONS`` card declares its unit inline — so the unit is read at the
  boundary and the conversion recorded (the input-parser precedent, M50; never a single
  assumed unit across blocks).
* **Energy** — ``electronic.total_energy`` maps the ``!    total energy`` value (Ry) through
  the ``_qe`` output core's ``total_energy_from_ry`` (QE's ``RYTOEV``, hand-pinned).
* **Forces** — ``dynamics.forces`` maps the ``Forces acting on atoms`` block (Ry/bohr →
  eV/Å); QE's forces are the forces acting on the atoms, the canonical convention, so no sign
  flip (``forces_from_ry_bohr``).
* **Stress (the M52 trap, D195)** — ``electronic.stress`` is computed from QE's native
  **Ry/bohr³** 3×3 block (QE prints the full tensor, not a Voigt-6 line), sign-flipped from
  QE's compression-positive convention to canonical tension-positive and converted by QE's own
  constants (``stress_from_qe`` — the sign verified against the ASE reference reader, never
  assumed); QE's **kbar** column is the within-file cross-check. ``_vasp`` is never imported.
* **Masses (D191's present-with-value discipline)** — declared ``atomic species`` masses
  promote to ``atoms.masses``; the verbatim declared table rides
  ``user_metadata.custom_global['qe_pw_out:atomic_species']``.
* **Per-step cells** — a step's own ``CELL_PARAMETERS`` card (the ``vc-relax``/``vc-md`` form)
  supplies that step's cell; a step without one reuses the running cell (the fixed-cell form).
* **``pbc = (T,T,T)``** by format definition, as a ``parse_notes`` entry.

**Error contract (Part 3 §5; D195/D196).** ``QEOUT_EMPTY`` (a truly empty file, or a
recognized header with no ``!    total energy`` line at all — a run with zero steps),
``QEOUT_UNRECOGNIZED_LAYOUT`` (the header cannot be recognized — no parseable version banner,
species table, counts, initial cell, or positions — or a step block is present-but-unparseable
in a way that is **not** a torn tail: refused, never a silent partial parse, **P1**; QE
layouts beyond 6.x/7.x land here with a corpus-contribution call), ``QEOUT_INCONSISTENT_STEP``
(an atom-keyed step block — force rows / position rows — whose row count disagrees with the
header's atom count: refused, never silently truncated to the shorter, **P3**),
``QEOUT_TRUNCATED`` (the file ends mid-step-block — a run killed while writing: recoverable
through the shared ``truncate_corrupt_tail`` scenario (Revision 1.15) via
``recovery_hint="truncate_at_last_valid_frame"`` and ``parse_recover`` (M52-S3, D197), never
by default — the plain read refuses, P1/P4), the warning ``QEOUT_UNCONVERGED`` (QE's own
statement that an SCF did not converge; the step's energy is still read present-with-value and
flagged, **P3**), and the warning ``QEOUT_UNMAPPED_BLOCK_CARRIED`` (a recognized-but-unmapped
diagnostic — the per-step ``total force`` scalar — carried verbatim, **P1**).

**S2 scope.** Both QE major layouts (6.x and 7.x) are read completely. The scanning anchors on
stable substrings and whitespace-splits (``str.split()``), never fixed byte columns, so the
documented 6.x↔7.x drift — whitespace/column differences, minor label wording (e.g.
``atomic species`` vs ``Atomic species``), header ordering — is tolerated; an unrecognized
layout or an atom-count-inconsistent step refuses; an unconverged SCF is flagged. The input-
echo cross-check runs against **both** layout renderings of the run (the go/no-go gate).

**S3 scope (D197).** A torn pw.x output — a run killed mid-step, leaving complete steps behind
a corrupt tail — refuses by default (``QEOUT_TRUNCATED`` with the shared
``truncate_at_last_valid_frame`` hint) and recovers through the existing ``truncate_corrupt_tail``
scenario, reusing the xdatcar/outcar ``truncate``-switch + ``parse_recover`` pattern verbatim:
no new recovery machinery. The streamed read holds one step resident at 10⁴-step scale, the
MLIP flagship example converts a ``vc-relax`` run to a validated extXYZ training file, and the
benchmark harness gains the two QE rows (measured, not gated).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO

import numpy as np

from xtalate.parsers._common import build_provenance
from xtalate.parsers._qe import (
    BOHR_TO_ANGSTROM,
    coordinate_system,
    lattice_from_cell_parameters,
    pbc_note,
    positions_cartesian,
    species_symbol,
)
from xtalate.parsers._qe.labels import (
    energy_parse_note,
    forces_from_ry_bohr,
    forces_parse_note,
    kbar_value,
    masses_parse_note,
    source_code_parse_note,
    step_cell_parse_note,
    step_positions_parse_note,
    stress_from_qe,
    stress_parse_note,
    total_energy_from_ry,
)
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    Cell,
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

FORMAT_ID = "qe_pw_out"

#: The custom_global key the verbatim declared ``atomic species`` table rides under
#: (label → [valence, mass, pseudopotential]) — the M50 ``qe_pw_in:atomic_species``
#: precedent: a declared declaration is never dropped (P1).
_ATOMIC_SPECIES_KEY = "qe_pw_out:atomic_species"
#: The per-frame carry key for the recognized-but-unmapped ``total force`` scalar.
_TOTAL_FORCE_KEY = "total_force"
#: The shared recovery hint a torn pw.x output carries: a run killed mid-step leaves the
#: complete steps as good science behind a corrupt tail, so the error is recoverable through
#: the existing ``truncate_corrupt_tail`` scenario (Revision 1.15; the xdatcar/outcar
#: pattern, D166/D197). ``conversion.parse_recovery`` maps this hint to that scenario — no
#: new recovery machinery.
_TRUNCATE_HINT = "truncate_at_last_valid_frame"

# A single float token, including Fortran exponent forms (-0.12345678E+02).
_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_TRIPLE = r"\(\s*([^)]+)\)"

#: The PWSCF program banner (`Program PWSCF v.7.2 (enter)`) — the declared program; the
#: verbatim line becomes simulation.source_code.
_VERSION_RE = re.compile(r"Program\s+PWSCF\s+v\.\d+\.\d+")
#: The `!    total energy =   -49.12345678 Ry` line — one per ionic step (and one for an
#: SCF-only run); the frame key. The SCF-iteration `total energy = …` line carries no `!`,
#: so anchoring on the `!` prefix never mistakes an iteration for a step.
_ENERGY_RE = re.compile(rf"!\s*total\s+energy\s*=\s*({_FLOAT})")
#: The declared lattice scale: `lattice parameter (alat)  =       9.4486307  a.u.` (bohr).
_ALAT_RE = re.compile(rf"lattice\s+parameter\s*\(\s*alat\s*\)\s*=\s*({_FLOAT})")
#: The counts: `number of atoms/cell      =            3` / `number of atomic types   =  2`.
_N_ATOMS_RE = re.compile(r"number\s+of\s+atoms\s*/\s*cell\s*=\s*(\d+)")
_N_TYPES_RE = re.compile(r"number\s+of\s+atomic\s+types\s*=\s*(\d+)")
#: The header's initial-positions table header: `site n.     atom   positions (bohr units)`.
_POSITIONS_UNIT_RE = re.compile(r"positions\s*\(\s*([a-z]+)\s+units\s*\)")
#: A row of the initial-positions table: `1  O  tau(   1) = (  x  y  z  )`.
_TAU_ROW_RE = re.compile(rf"tau\s*\(\s*\d+\s*\)\s*=\s*{_TRIPLE}")
#: A row of the crystal-axes block: `a(1) = (   1.000000   0.000000   0.000000 )`.
_AXES_ROW_RE = re.compile(rf"[abc]\(\d+\)\s*=\s*{_TRIPLE}")
#: The per-step force row: `atom   1 type  1   force =    x    y    z`.
_FORCE_ROW_RE = re.compile(rf"force\s*=\s*({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})")
#: The recognized-but-unmapped `total force = …` scalar (carried verbatim per frame, P1).
_TOTAL_FORCE_RE = re.compile(rf"total\s+force\s*=\s*({_FLOAT})")
#: QE's own statement that an SCF did not converge — `convergence NOT achieved after N
#: iterations` (printed when ``scf_must_converge = .false.``, or when a relaxation step's SCF
#: is allowed to run on): the QEOUT_UNCONVERGED warning anchor (D196). The energy of the step
#: is still read present-with-value (P3) — the honesty is in surfacing the flag, never in
#: withholding the value.
_UNCONVERGED_RE = re.compile(
    r"convergence\s+not\s+achieved\s+after\s+(\d+)\s+iterations", re.IGNORECASE
)

#: The per-card unit annotation, the input parser's spelling (brace/paren/bare) — the output
#: uses the paren form (`ATOMIC_POSITIONS (angstrom)`).
_CARD_UNIT_RE = re.compile(r"[{(]?\s*([A-Za-z_][A-Za-z0-9_]*)")
#: A CELL_PARAMETERS alat annotation: `CELL_PARAMETERS (alat=  9.44863066)` — the alat value
#: rides the card header itself.
_CELL_ALAT_RE = re.compile(rf"alat\s*=\s*({_FLOAT})")

_PBC_NOTE = pbc_note()
_POSITIONS_NOTE_LEAD = (
    "Initial positions read from the site table (site n. atom …), which declares its unit: "
)

_LOSSY_NOTES = [
    "The reciprocal-axes block is not mapped to a canonical field.",
    "K-point listings are not mapped to a canonical field.",
    "SCF-iteration diagnostics (iteration #, ecut, beta, scf accuracy) are not mapped.",
    "celldm(1..6) echoes are not mapped beyond the derived initial cell.",
    "The valence and pseudopotential columns of the species table ride the verbatim carry, "
    "not canonical fields.",
    "The 'total SCF correction' scalar is not mapped beyond the carried 'total force'.",
    "Timing diagnostics (total cpu time) are not mapped to a canonical field.",
]


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


def _carry_warning(key: str, *, location: str) -> ParseIssue:
    return ParseIssue(
        severity="warning",
        code="QEOUT_UNMAPPED_BLOCK_CARRIED",
        message=(
            f"the '{key}' diagnostic has no canonical field; carried verbatim in "
            f"user_metadata.custom_per_frame['{FORMAT_ID}:{key}']"
        ),
        location=location,
    )


def _line_reader(stream: BinaryIO) -> Iterator[str]:
    """Yield decoded lines off the raw byte stream one at a time — line-at-a-time is what
    keeps the streaming parser's peak memory bounded by a step instead of the file. A
    non-UTF-8 byte raises the structured ``ParseError`` of Part 3 §5 at the point of failure
    (the shared text-format encoding-error contract, ``_common.decode_text``)."""
    while True:
        raw = stream.readline()
        if raw == b"":
            return
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                "QEOUT_ENCODING_ERROR",
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); qe_pw_out is a "
                "text format",
            ) from exc


class _Lookahead:
    """One-line lookahead over the decoded line stream.

    The atom-count guard (QEOUT_INCONSISTENT_STEP) must inspect the line *after* a block's
    rows without consuming it — a block that continues past the header's atom count is
    refused, never silently truncated — so the step scanner reads through this wrapper.
    ``peek_nonblank`` inspects the next non-blank line without consuming (it is buffered and
    returned by the next consume); ``next_raw`` consumes the next line *as-is*, blank or not
    — the row readers need the blanks, because a blank line before a block's declared row
    count means the block ended short (a count disagreement), while a *non-blank* line that
    is not a row means the block is malformed (an unrecognized layout).
    """

    def __init__(self, lines: Iterator[str]) -> None:
        self._lines = iter(lines)
        self._buffered: str | None = None

    def peek_nonblank(self) -> str | None:
        while self._buffered is None:
            line = next(self._lines, None)
            if line is None:
                return None
            if line.strip():
                self._buffered = line
                break
        return self._buffered

    def next_raw(self) -> str | None:
        if self._buffered is not None:
            line = self._buffered
            self._buffered = None
            return line
        return next(self._lines, None)

    def next_nonblank(self) -> str | None:
        line = self.peek_nonblank()
        self._buffered = None
        return line


def _is_float_row(line: str, *, col_offset: int, ncols: int) -> bool:
    """Whether the line carries ``ncols`` numeric tokens at ``col_offset`` — the row
    predicate shared by the float-block readers (and the over-long-block guard)."""
    tokens = line.split()
    if len(tokens) < col_offset + ncols:
        return False
    try:
        for token in tokens[col_offset : col_offset + ncols]:
            float(token)
    except ValueError:
        return False
    return True


def _card_unit(rest: str) -> str | None:
    """The unit/option annotation on a card header's remainder, or ``None`` when the
    remainder is empty — the input parser's spelling (brace/paren/bare, lowercased)."""
    match = _CARD_UNIT_RE.match(rest.strip())
    return match.group(1).lower() if match else None


def _cell_card_unit(rest: str) -> tuple[str, float | None]:
    """A ``CELL_PARAMETERS`` card's ``(unit, alat_bohr)`` from its header remainder.

    The output's ``CELL_PARAMETERS`` card either declares a plain unit (``(angstrom)`` /
    ``(bohr)``) or carries its alat scale inline — ``(alat=  9.44863066)`` — so an alat-relative
    card resolves its own scale (bohr), never the header's (a vc-relax cell can drift away from
    the initial alat).
    """
    match = _CELL_ALAT_RE.search(rest)
    if match is not None:
        return "alat", float(match.group(1))
    unit = _card_unit(rest)
    # A bare CELL_PARAMETERS card reads as alat per QE's documented default (the caller
    # resolves the scale from the running alat).
    return (unit or "alat"), None


def _triple_values(line: str, pattern: re.Pattern[str]) -> list[float] | None:
    """The three floats inside a parenthesized row (``(  x  y  z  )``), or ``None`` when the
    row does not carry a parseable triple."""
    match = pattern.search(line)
    if match is None:
        return None
    tokens = match.group(1).split()
    if len(tokens) != 3:
        return None
    try:
        return [float(t) for t in tokens]
    except ValueError:
        return None


def _read_float_rows(
    lines: _Lookahead,
    count: int,
    *,
    ncols: int,
    what: str,
    location: str,
    col_offset: int = 0,
    atom_keyed: bool = False,
) -> np.ndarray:
    """``count`` rows of ``ncols`` numeric columns starting at ``col_offset`` (blank lines
    skipped; an ATOMIC_POSITIONS row's leading label is skipped with ``col_offset=1``).

    M52-S2's drift discipline (D196):

    * a **non-numeric / too-short row** while the stream continues — a block that is
      present-but-unparseable — is a ``QEOUT_UNRECOGNIZED_LAYOUT`` refusal (a layout beyond
      6.x/7.x; never a silent partial read, P1);
    * a block that **ends before ``count`` rows** while the stream continues is the same
      refusal (the shorter form is never silently accepted);
    * a block that **continues past ``count`` rows** is refused with
      ``QEOUT_INCONSISTENT_STEP`` for an *atom-keyed* block (force/position rows — the step's
      atom count disagrees with the header, P3) or ``QEOUT_UNRECOGNIZED_LAYOUT`` for a
      fixed-size block (the 3×3 cell/tensor);
    * only the stream **ending** mid-block stays ``QEOUT_MISSING_BLOCK`` — the torn-tail
      case, whose ``QEOUT_TRUNCATED`` recovery is M52-S3.
    """
    rows: list[list[float]] = []
    while len(rows) < count:
        line = lines.next_raw()
        if line is None:
            # The file ends mid-block: a run killed while writing this step leaves the earlier
            # complete steps as good science — the recoverable torn tail (QEOUT_TRUNCATED,
            # M52-S3, D197), routed through the shared truncate_corrupt_tail scenario. The
            # honest *default* read still refuses (a recoverable error is an error until the
            # user chooses recovery), and a structurally wrong block is never this (D196).
            raise _error(
                "QEOUT_TRUNCATED",
                f"{what} ended after {len(rows)} of {count} rows ({location}) — the file "
                "ends mid-block (a run killed while writing this step); the complete earlier "
                "steps are kept only under the explicit truncate_corrupt_tail choice, never by "
                "default (P1/P4)",
                location=location,
                hint=_TRUNCATE_HINT,
            )
        if not line.strip():
            if not rows:
                continue  # a blank between the block header and its first row is formatting noise
            # A blank line once rows have begun: the block ended short (the stream
            # continues with other blocks) — a count disagreement, never a shorter block.
            _raise_block_disagreement(
                atom_keyed=atom_keyed,
                what=what,
                detail=f"the block ended after {len(rows)} of {count} rows ({location})",
                location=location,
                n_expected=count,
                n_found=len(rows),
            )
        if not _is_float_row(line, col_offset=col_offset, ncols=ncols):
            raise _error(
                "QEOUT_UNRECOGNIZED_LAYOUT",
                f"{what} is present but unparseable as a 6.x/7.x block ({location}): row "
                f"{len(rows) + 1} is not numeric ({line.strip()!r}) — refused, never a "
                "silent partial read (P1); a QE layout beyond 6.x/7.x should be contributed "
                "to the golden corpus to extend the read (M53)",
                location=location,
            )
        rows.append([float(t) for t in line.split()[col_offset : col_offset + ncols]])
    extra = lines.peek_nonblank()
    if extra is not None and _is_float_row(extra, col_offset=col_offset, ncols=ncols):
        _raise_block_disagreement(
            atom_keyed=atom_keyed,
            what=what,
            detail=f"a {count + 1}-th row follows the declared {count} ({location}): "
            f"{extra.strip()!r}",
            location=location,
            n_expected=count,
            n_found=count,
        )
    return np.asarray(rows, dtype=float)


def _raise_block_disagreement(
    *,
    atom_keyed: bool,
    what: str,
    detail: str,
    location: str,
    n_expected: int,
    n_found: int,
) -> None:
    """The refusal for a present-but-unparseable / wrong-sized block (D196). An atom-keyed
    block whose row count disagrees with the header's atom count is the
    ``QEOUT_INCONSISTENT_STEP`` refusal — a structural inconsistency, never a torn tail (P3);
    a fixed-size block that is malformed is ``QEOUT_UNRECOGNIZED_LAYOUT`` — a layout beyond
    6.x/7.x, refused rather than partial-parsed (P1)."""
    if atom_keyed:
        raise _error(
            "QEOUT_INCONSISTENT_STEP",
            f"{what} carries {n_found} rows but the header declares {n_expected} atoms "
            f"({location}): {detail} — a step whose atom count disagrees with the header is "
            "refused, never silently truncated to the shorter (P3)",
            location=location,
        )
    raise _error(
        "QEOUT_UNRECOGNIZED_LAYOUT",
        f"{what} is present but unparseable as a 6.x/7.x block ({location}): {detail} — "
        "refused, never a silent partial read (P1); a QE layout beyond 6.x/7.x should be "
        "contributed to the golden corpus to extend the read (M53)",
        location=location,
    )


def _read_force_rows(lines: _Lookahead, n_atoms: int, *, location: str) -> np.ndarray:
    """The ``n_atoms`` rows of the ``Forces acting on atoms`` block — each
    ``atom N type T   force =   x   y   z`` (Ry/bohr) — as the (N, 3) numeric matrix, with
    M52-S2's atom-count guard: a step whose force rows disagree with the header atom count is
    refused ``QEOUT_INCONSISTENT_STEP`` (never silently truncated, P3)."""
    rows: list[list[float]] = []
    while len(rows) < n_atoms:
        line = lines.next_raw()
        if line is None:
            raise _error(
                "QEOUT_TRUNCATED",
                f"the force block ended after {len(rows)} of {n_atoms} atoms ({location}) — "
                "the file ends mid-block (a run killed while writing this step); the complete "
                "earlier steps are kept only under the explicit truncate_corrupt_tail choice, "
                "never by default (P1/P4)",
                location=location,
                hint=_TRUNCATE_HINT,
            )
        if not line.strip():
            if not rows:
                continue  # a blank between the header and its first row is formatting noise
            # A blank line once rows have begun: the block ended short (the stream
            # continues) — a count disagreement, never a silently shorter block.
            _raise_block_disagreement(
                atom_keyed=True,
                what="the force block",
                detail=f"the block ended after {len(rows)} of {n_atoms} atoms ({location})",
                location=location,
                n_expected=n_atoms,
                n_found=len(rows),
            )
        match = _FORCE_ROW_RE.search(line)
        if match is None:
            raise _error(
                "QEOUT_UNRECOGNIZED_LAYOUT",
                f"the force block is present but unparseable as a 6.x/7.x block ({location}): "
                f"row {len(rows) + 1} is not the recognized 'atom N type T force = x y z' form "
                f"({line.strip()!r}) — refused, never a silent partial read (P1); a QE layout "
                "beyond 6.x/7.x should be contributed to the golden corpus to extend the read "
                "(M53)",
                location=location,
            )
        rows.append([float(match.group(1)), float(match.group(2)), float(match.group(3))])
    extra = lines.peek_nonblank()
    if extra is not None and _FORCE_ROW_RE.search(extra) is not None:
        _raise_block_disagreement(
            atom_keyed=True,
            what="the force block",
            detail=f"a {n_atoms + 1}-th force row follows the header's {n_atoms} atoms "
            f"({location}): {extra.strip()!r}",
            location=location,
            n_expected=n_atoms,
            n_found=n_atoms,
        )
    return np.asarray(rows, dtype=float)


@dataclass
class _Header:
    """Everything parsed eagerly before the first ionic step: the declared program banner, the
    per-atom symbols and masses (hence the atom count), the initial lattice (the running cell
    fixed-cell steps reuse) and the initial positions (the running positions a step without its
    own ATOMIC_POSITIONS card reuses). ``species`` keeps the declared table verbatim (label,
    valence, mass, pseudopotential) for the never-dropped carry (P1)."""

    version: str
    species: list[tuple[str, float, float, str]]
    symbols: list[str]
    masses: np.ndarray
    n_atoms: int
    lattice: np.ndarray
    alat: float  # the resolved initial alat in Å
    initial_positions: np.ndarray
    initial_positions_unit: str
    notes: list[str]


def _finalize_header(
    version: str | None,
    species: list[tuple[str, float, float, str]],
    n_atoms: int | None,
    n_types: int | None,
    alat_bohr: float | None,
    axes_rows: np.ndarray | None,
    positions: list[tuple[str, list[float]]] | None,
    positions_unit: str | None,
) -> _Header:
    """Validate the eagerly-scanned header and build the ``_Header``.

    A recognized context missing an expected block — no species table, no counts, no initial
    cell, no initial positions — is a ``ParseError`` under the §5 contract, never a defaulted
    field (P3). The per-atom symbols come from the **site table's per-atom labels** (the
    species table lists the *species*, not the atoms — ``number of atoms/cell`` is the total
    and the site rows carry each atom's label); each label resolves through QE's documented
    label rule (the M50 input parser's, ``sdk.qe.species_symbol`` — decorated labels resolve
    identically, each resolution recorded), and each atom's mass comes from its label's
    declared species row (present-with-value, P3). A label that resolves to no element refuses
    naming the value (the same ``missing_species`` recovery applies as to the input parser,
    D191).
    """
    if version is None:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            "file contains no recognizable pw.x run (no Program PWSCF version banner found); "
            "QE layouts beyond 6.x/7.x are refused, never a silent partial parse (P1) — "
            "contribute the file to the golden corpus to extend the read (M53)",
        )
    if not species:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            "no atomic species found (an 'atomic species   valence    mass   pseudopotential' "
            "table is required) — the header cannot be recognized as a 6.x/7.x pw.x run; "
            "refused, never a silent partial parse (P1); contribute the file to the golden "
            "corpus to extend the read (M53)",
        )
    if n_atoms is None:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            "the atom count is missing ('number of atoms/cell' is required) — the header "
            "cannot be recognized as a 6.x/7.x pw.x run; refused, never a silent partial "
            "parse (P1); contribute the file to the golden corpus to extend the read (M53)",
        )
    if n_atoms == 0:
        raise _error("QEOUT_UNRECOGNIZED_LAYOUT", "header declares zero atoms — not a run")
    if n_types is not None and n_types != len(species):
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            f"header declares {n_types} atomic types but the species table lists "
            f"{len(species)} species — the header cannot be recognized as a 6.x/7.x pw.x run; "
            "refused, never a silent partial parse (P1)",
        )
    species_by_label = {label: (valence, mass, pseudo) for label, valence, mass, pseudo in species}
    if positions is None or positions_unit is None:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            "no initial positions found (the 'positions (<unit> units)' site table is "
            "required) — the header cannot be recognized as a 6.x/7.x pw.x run; refused, "
            "never a silent partial parse (P1); contribute the file to the golden corpus to "
            "extend the read (M53)",
        )
    if len(positions) != n_atoms:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            f"the initial positions table carries {len(positions)} rows for "
            f"{n_atoms} atoms — counts must agree; the header cannot be recognized as a "
            "6.x/7.x pw.x run, never a silent partial parse (P1)",
        )
    symbols: list[str] = []
    masses: list[float] = []
    notes: list[str] = []
    for label, _xyz in positions:
        if label not in species_by_label:
            raise _error(
                "QEOUT_UNRECOGNIZED_LAYOUT",
                f"site table labels an atom {label!r} that the atomic species table does not "
                f"declare (species: {', '.join(sorted(species_by_label))}) — the header "
                "cannot be recognized as a 6.x/7.x pw.x run; refused, never a silent partial "
                "parse (P1)",
                location="initial positions table",
            )
        symbol, _ = species_symbol(label)
        if symbol is None:
            raise _error(
                "QEOUT_UNRECOGNIZED_LAYOUT",
                f"site table label {label!r} resolves to no element (QE's label rule: the "
                "leading 1–2 characters that form an element symbol) — the species table "
                "cannot be recognized as a 6.x/7.x pw.x run; supply a label→element "
                "species_map through the existing missing_species recovery to complete the read",
                location="initial positions table",
            )
        symbols.append(symbol)
        masses.append(float(species_by_label[label][1]))
        notes.append(
            f"site-table label {label!r} resolves to element {symbol} (QE's documented label "
            f"rule); its declared mass {species_by_label[label][1]} u is promoted to "
            "atoms.masses."
        )
    notes.append(
        "The declared atomic-species table (label → valence, mass, pseudopotential) rides "
        "verbatim in user_metadata.custom_global['qe_pw_out:atomic_species'] — nothing "
        "declared is dropped (P1)."
    )
    if alat_bohr is None:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            "the initial lattice scale is missing ('lattice parameter (alat)' is required) — "
            "the header cannot be recognized as a 6.x/7.x pw.x run; refused, never a silent "
            "partial parse (P1); contribute the file to the golden corpus to extend the read "
            "(M53)",
        )
    alat = alat_bohr * BOHR_TO_ANGSTROM
    if axes_rows is None:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            "no initial cell found (the 'crystal axes: (cart. coord. in units of alat)' block "
            "is required) — the header cannot be recognized as a 6.x/7.x pw.x run; refused, "
            "never a silent partial parse (P1); contribute the file to the golden corpus to "
            "extend the read (M53)",
        )
    lattice = axes_rows * alat
    notes.append(
        f"Initial cell read from the 'crystal axes' block in units of alat and converted to Å "
        f"(alat = {alat_bohr} bohr × {BOHR_TO_ANGSTROM} = {alat} Å)."
    )
    coords = np.asarray([xyz for _, xyz in positions], dtype=float)
    try:
        initial_positions, pos_note = positions_cartesian(
            coords, positions_unit, lattice=lattice, alat=alat
        )
    except ValueError as exc:
        raise _error(
            "QEOUT_UNRECOGNIZED_LAYOUT",
            f"the declared positions unit {positions_unit!r} cannot be converted — the "
            f"header cannot be recognized as a 6.x/7.x pw.x run ({exc}); refused, never a "
            "silent partial parse (P1)",
            location="initial positions table",
        ) from exc
    notes.append(_POSITIONS_NOTE_LEAD + pos_note)
    return _Header(
        version=version,
        species=species,
        symbols=symbols,
        masses=np.asarray(masses, dtype=float),
        n_atoms=n_atoms,
        lattice=lattice,
        alat=alat,
        initial_positions=initial_positions,
        initial_positions_unit=positions_unit,
        notes=notes,
    )


def _read_header(lines: Iterator[str]) -> tuple[_Header | None, str | None, list[str]]:
    """Scan the header eagerly and stop at the first ``!    total energy`` line (the first
    ionic step's energy — the step region begins there).

    Returns ``(header, pending_line, unconverged)``: ``pending_line`` is the already-consumed
    step line (the first ``!    total energy``) the step loop must start from — it is handed
    back, never dropped; ``unconverged`` collects QE's own ``convergence NOT achieved``
    statements verbatim, because the **first step's SCF preamble is consumed by this scan**
    and its unconverged flag must not be lost (D196). ``header`` is ``None`` when the file
    ends with a recognized banner but no energy line ever appears (the caller raises
    ``QEOUT_EMPTY`` — a recognized header with zero steps). All header anchors are collected
    wherever they appear (the banner, the species table, the counts, alat, the crystal-axes
    block, the initial-positions table); everything else in the preamble is skipped as
    diagnostic noise.
    """
    version: str | None = None
    species: list[tuple[str, float, float, str]] = []
    n_atoms: int | None = None
    n_types: int | None = None
    alat_bohr: float | None = None
    axes_rows: list[list[float]] = []
    positions: list[tuple[str, list[float]]] = []
    positions_unit: str | None = None
    reading_species = False
    reading_axes = False
    reading_positions = False
    unconverged: list[str] = []
    for line in lines:
        if _ENERGY_RE.search(line):
            return (
                _finalize_header(
                    version,
                    species,
                    n_atoms,
                    n_types,
                    alat_bohr,
                    np.asarray(axes_rows, dtype=float) if axes_rows else None,
                    positions if positions else None,
                    positions_unit,
                ),
                line,
                unconverged,
            )
        if _UNCONVERGED_RE.search(line) is not None:
            # The first step's SCF preamble lives in the header region — its unconverged
            # statement is collected here so the flag survives (D196).
            unconverged.append(line.strip())
        if version is None and _VERSION_RE.search(line):
            version = line.strip()
        if "atomic species" in line.lower():
            reading_species = True
            continue
        if reading_species:
            tokens = line.split()
            if len(tokens) in (4, 5) and _is_float(tokens[1]):
                # The pseudopotential column is often `O( 1.00)` — the label and its parenthesized
                # factor split on whitespace, so a 5-token row is the same 4-column declaration
                # (rejoined verbatim with its separating space).
                pseudo = tokens[3] if len(tokens) == 4 else tokens[3] + " " + tokens[4]
                species.append((tokens[0], float(tokens[1]), float(tokens[2]), pseudo))
                continue
            reading_species = False
        if n_atoms is None:
            match = _N_ATOMS_RE.search(line)
            if match:
                n_atoms = int(match.group(1))
        if n_types is None:
            match = _N_TYPES_RE.search(line)
            if match:
                n_types = int(match.group(1))
        if alat_bohr is None:
            match = _ALAT_RE.search(line)
            if match:
                alat_bohr = float(match.group(1))
        if "crystal axes" in line:
            reading_axes = True
            continue
        if reading_axes:
            values = _triple_values(line, _AXES_ROW_RE)
            if values is not None:
                axes_rows.append(values)
                continue
            if len(axes_rows) >= 3:
                reading_axes = False
        match = _POSITIONS_UNIT_RE.search(line)
        if match is not None:
            positions_unit = match.group(1).lower()
            reading_positions = True
            continue
        if reading_positions:
            label, xyz = _tau_row(line)
            if xyz is not None:
                positions.append((label, xyz))
                continue
            if positions and len(positions) >= 1:
                reading_positions = False
    if version is not None:
        # A recognized banner but the file ends before any energy line. Validate the header
        # first: a *complete* header is a recognized run with zero steps (QEOUT_EMPTY — no
        # ionic step at all), while an incomplete/unparseable one is an unrecognized layout
        # (QEOUT_UNRECOGNIZED_LAYOUT — M52-S2's refusal, never a silent partial parse, P1).
        _finalize_header(
            version,
            species,
            n_atoms,
            n_types,
            alat_bohr,
            np.asarray(axes_rows, dtype=float) if axes_rows else None,
            positions if positions else None,
            positions_unit,
        )
        return None, None, unconverged
    raise _error(
        "QEOUT_UNRECOGNIZED_LAYOUT",
        "file contains no recognizable pw.x run (no Program PWSCF version banner and no "
        "energy line found); QE layouts beyond 6.x/7.x are refused, never a silent partial "
        "parse (P1) — contribute the file to the golden corpus to extend the read (M53)",
    )


def _is_float(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False


def _tau_row(line: str) -> tuple[str, list[float] | None]:
    """A site-table row's ``(label, [x, y, z])`` — ``1  O  tau(   1) = (  x  y  z  )`` — or
    ``(label, None)`` when the line is not a site row."""
    values = _triple_values(line, _TAU_ROW_RE)
    if values is None:
        return "", None
    tokens = line.split()
    label = tokens[1] if len(tokens) > 1 else ""
    return label, values


def _read_stress_block(lines: _Lookahead, *, location: str) -> np.ndarray:
    """The step's ``total   stress`` 3×3 tensor — three rows of three Ry/bohr³ values plus the
    per-row kbar column — mapped to canonical tension-positive eV/Å³.

    QE's **kbar** column is the within-file cross-check (D195): the file's own two statements
    of the same tensor must agree after conversion, so a disagreement beyond rounding is a
    present-but-unparseable block — refused ``QEOUT_UNRECOGNIZED_LAYOUT``, never silently
    trusted (P1). A malformed/oversized stress block is the same refusal (a 3×3 tensor is
    fixed-size, so a wrong row count is a layout problem, not an atom-count one).
    """
    rows = _read_float_rows(
        lines, 3, ncols=4, what="stress block", location=location, atom_keyed=False
    )
    kbar_col = rows[:, 3]
    for r, printed_kbar in enumerate(kbar_col):
        computed = kbar_value(float(rows[r][0]))
        # QE prints the kbar column to ~5 significant digits; a disagreement beyond that means
        # the file's own two statements of the tensor disagree.
        if abs(printed_kbar - computed) > max(1e-3, abs(computed) * 1e-3):
            raise _error(
                "QEOUT_UNRECOGNIZED_LAYOUT",
                f"the stress kbar column ({printed_kbar!r}) disagrees with the Ry/bohr³ value "
                f"({computed!r} kbar after conversion) beyond rounding ({location}) — the "
                "file's own two statements of the tensor disagree and the block cannot be "
                "read as a 6.x/7.x stress block; refused, never silently trusted (P1)",
                location=location,
            )
    return stress_from_qe(rows[:, :3])


def _build_frame(
    header: _Header,
    *,
    frame_index: int,
    energy: float,
    forces: np.ndarray | None,
    stress: np.ndarray | None,
    step_positions: np.ndarray | None,
    cell: np.ndarray | None,
    carry: dict[str, Any],
) -> StreamFrame:
    positions = step_positions if step_positions is not None else header.initial_positions
    lattice = cell if cell is not None else header.lattice
    frame = Frame(
        index=frame_index,
        atoms=AtomsBlock(
            symbols=list(header.symbols),
            positions=positions,
            masses=header.masses,
        ),
        cell=Cell(lattice_vectors=lattice, pbc=(True, True, True)),
        dynamics=Dynamics(forces=forces),
        electronic=Electronic(total_energy=total_energy_from_ry(energy), stress=stress),
    )
    return StreamFrame(frame=frame, per_frame_custom=carry)


def _steps(
    lines: Iterator[str], header: _Header, issues: list[ParseIssue]
) -> Iterator[StreamFrame]:
    """Yield one ``StreamFrame`` per ``!    total energy`` line, lazily, one step resident.

    Real pw.x order per ionic step: the SCF iterations, the ``!    total energy`` line, the
    ``Forces acting on atoms`` block, the ``total   stress`` block, the updated
    ``ATOMIC_POSITIONS`` card and (for ``vc-relax``/``vc-md``) the updated ``CELL_PARAMETERS``
    card. The ``!`` line is the frame boundary: blocks are accumulated into the current step
    until the next ``!`` line (or EOF) arrives, then the frame is emitted. The SCF-iteration
    preamble of the next step (before its ``!`` line) is skipped as diagnostic noise — except
    QE's own ``convergence NOT achieved`` statement, which fires the ``QEOUT_UNCONVERGED``
    warning (D196) while the step's energy is still read present-with-value (P3).

    Lines are read through ``_Lookahead`` so the atom-count guard can inspect the line after a
    block's rows without consuming it (QEOUT_INCONSISTENT_STEP, D196).
    """
    lookahead = _Lookahead(lines)
    frame_index = 0
    energy: float | None = None
    forces: np.ndarray | None = None
    stress: np.ndarray | None = None
    step_positions: np.ndarray | None = None
    cell: np.ndarray | None = None
    carry: dict[str, Any] = {}
    while (line := lookahead.next_nonblank()) is not None:
        match = _ENERGY_RE.search(line)
        if match is not None:
            if energy is not None:
                yield _build_frame(
                    header,
                    frame_index=frame_index,
                    energy=energy,
                    forces=forces,
                    stress=stress,
                    step_positions=step_positions,
                    cell=cell,
                    carry=carry,
                )
                frame_index += 1
                forces = None
                stress = None
                step_positions = None
                cell = None
                carry = {}
            energy = float(match.group(1))
            continue
        unconverged = _UNCONVERGED_RE.search(line)
        if unconverged is not None:
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="QEOUT_UNCONVERGED",
                    message=(
                        "QE states the SCF did not converge: "
                        f"{line.strip()!r} — the step's energy is still read "
                        "(present-with-value, P3) and flagged so a training set sees it"
                    ),
                    location=f"frame {frame_index}",
                )
            )
            continue
        if energy is None:
            continue  # preamble between steps (the next step's SCF iterations)
        if "Forces acting on atoms" in line:
            forces = forces_from_ry_bohr(
                _read_force_rows(lookahead, header.n_atoms, location=f"frame {frame_index}")
            )
        elif "total   stress" in line:
            stress = _read_stress_block(lookahead, location=f"frame {frame_index}")
        elif "ATOMIC_POSITIONS" in line:
            unit = _card_unit(line.split("ATOMIC_POSITIONS", 1)[1]) or "alat"
            rows = _read_float_rows(
                lookahead,
                header.n_atoms,
                ncols=3,
                what="ATOMIC_POSITIONS card",
                location=f"frame {frame_index}",
                col_offset=1,
                atom_keyed=True,
            )
            try:
                step_positions, _ = positions_cartesian(
                    rows, unit, lattice=header.lattice, alat=header.alat
                )
            except ValueError as exc:
                raise _error(
                    "QEOUT_UNRECOGNIZED_LAYOUT",
                    f"the step's ATOMIC_POSITIONS card is present but unparseable as a 6.x/7.x "
                    f"block ({exc}); refused, never a silent partial read (P1)",
                    location=f"frame {frame_index}",
                ) from exc
        elif "CELL_PARAMETERS" in line:
            unit, alat_bohr = _cell_card_unit(line.split("CELL_PARAMETERS", 1)[1])
            rows = _read_float_rows(
                lookahead,
                3,
                ncols=3,
                what="CELL_PARAMETERS card",
                location=f"frame {frame_index}",
                atom_keyed=False,
            )
            alat_ang = alat_bohr * BOHR_TO_ANGSTROM if alat_bohr is not None else header.alat
            try:
                cell, _ = lattice_from_cell_parameters(rows, unit or "alat", alat=alat_ang)
            except ValueError as exc:
                raise _error(
                    "QEOUT_UNRECOGNIZED_LAYOUT",
                    f"the step's CELL_PARAMETERS card is present but unparseable as a 6.x/7.x "
                    f"block ({exc}); refused, never a silent partial read (P1)",
                    location=f"frame {frame_index}",
                ) from exc
        else:
            total_force = _TOTAL_FORCE_RE.search(line)
            if total_force is not None:
                carry[f"{FORMAT_ID}:{_TOTAL_FORCE_KEY}"] = float(total_force.group(1))
                issues.append(_carry_warning(_TOTAL_FORCE_KEY, location=f"frame {frame_index}"))
    if energy is not None:
        yield _build_frame(
            header,
            frame_index=frame_index,
            energy=energy,
            forces=forces,
            stress=stress,
            step_positions=step_positions,
            cell=cell,
            carry=carry,
        )


class QePwOutParser(ParserPlugin):
    """Quantum ESPRESSO pw.x output reader (Part 3 §3; v1.4 M52-S1). Parser-only (D159)."""

    format_id = FORMAT_ID
    format_name = "Quantum ESPRESSO pw.x output"
    version = "0.1.0"
    file_extensions = ()  # pw.x output is a conventional *name* (.out), not an extension.

    def sniff(self, head: bytes, filename: str | None) -> float:
        # Content-first: the PWSCF program banner is the decisive anchor — only a pw.x output
        # carries `Program PWSCF` (the input parser defers to it, D195), and many formats use
        # a `.out` filename, so the name alone is weak (and never decisive on its own).
        text = head.decode("utf-8", errors="replace")
        if _VERSION_RE.search(text):
            return 1.0
        if "ATOMIC_POSITIONS" in text and "Forces acting on atoms" in text:
            return 0.8
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56) — the
        streamed and whole-file readings are one code path and cannot diverge."""
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

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
        """Recover a pw.x output whose tail is a torn write by keeping the valid prefix
        (``truncate_at_last_valid_frame`` → ``truncate``, Part 4 §3.3; v1.4 M52-S3, D197).

        The characteristic pw.x failure: a run killed while writing ionic step *k*, so steps
        0..k-1 are perfectly good science behind a corrupt tail. Only ``truncate`` reaches
        here — ``abort`` is the caller declining to recover, handled in the orchestration
        (``conversion.parse_recovery``) — and only the ``truncate_at_last_valid_frame`` hint
        is handled. Re-reads through the *same* streaming path in truncate mode, so the kept
        prefix is read by exactly the code that reads an intact file, and the truncation is
        recorded as a warning ``ParseIssue`` — the dropped tail is never silent (P1). No new
        recovery machinery: the shared ``truncate_corrupt_tail`` scenario (Revision 1.15) is
        reused verbatim, the xdatcar/outcar pattern (D166) applied to ``qe_pw_out``.
        """
        if hint != _TRUNCATE_HINT:
            raise NotImplementedError(f"qe_pw_out parse_recover does not handle hint {hint!r}")
        if choice != "truncate":
            raise NotImplementedError(
                f"qe_pw_out parse_recover applies only the 'truncate' choice (got {choice!r})"
            )
        frame_stream = self.parse_stream(stream, filename=filename, truncate=True)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def parse_stream(
        self, stream: BinaryIO, *, filename: str | None, truncate: bool = False
    ) -> FrameStream:
        """Header-eager, step-lazy pw.x output parse (M52-S1/S3; Part 3 §2).

        ``truncate`` is the internal switch ``parse_recover`` sets to apply the caller's
        ``truncate_at_last_valid_frame`` choice: a recoverable mid-stream error then *ends*
        the stream at the last good step (recording a ``QEOUT_TRUNCATED`` warning) instead of
        propagating. It is not part of the ``ParserPlugin.parse_stream`` contract — callers
        reach it through ``parse_recover``, so the default read stays the honest one that
        refuses a corrupt file.
        """
        head = stream.read(4096)
        if not head.strip():
            raise _error("QEOUT_EMPTY", "file is empty")
        stream.seek(0)
        lines = _line_reader(stream)
        issues: list[ParseIssue] = []
        header, pending_line, unconverged = _read_header(lines)
        if header is None:
            raise _error(
                "QEOUT_EMPTY",
                "file contains no ionic step (no '!    total energy' line)",
            )
        for statement in unconverged:
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="QEOUT_UNCONVERGED",
                    message=(
                        "QE states the SCF did not converge: "
                        f"{statement!r} — the step's energy is still read "
                        "(present-with-value, P3) and flagged so a training set sees it"
                    ),
                    location="frame 0",
                )
            )
        stream_header = _build_stream_header(header, filename)
        if pending_line is not None:
            # The header scan already consumed the first step's energy line — hand it back so
            # the step loop starts from it (a consumed line is never dropped).
            lines = itertools.chain((pending_line,), lines)

        def _frames() -> Iterator[StreamFrame]:
            yielded = 0
            try:
                for frame in _steps(lines, header, issues):
                    yielded += 1
                    yield frame
            except ParseError as exc:
                # Truncate mode: a *recoverable* mid-stream error ends the stream at the last
                # good step instead of propagating. Two guards keep this honest: only errors
                # the parser itself marked recoverable are swallowed — a structurally wrong
                # file (a QEOUT_INCONSISTENT_STEP) still raises, because that is not a torn
                # tail — and the truncation is recorded as a warning so the dropped tail is
                # never silent (P1).
                issue = exc.issues[0]
                if not (truncate and issue.recovery_hint == _TRUNCATE_HINT):
                    raise
                if yielded == 0:
                    # Truncating to nothing is not a recovery: there is no valid prefix to
                    # keep, so the honest answer is the original error — never an empty frame
                    # list that would escape the §5 contract into a raw pydantic error.
                    raise
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="QEOUT_TRUNCATED",
                        message=(
                            "kept the valid ionic steps and discarded the corrupt tail "
                            f"({issue.code}: {issue.message})"
                        ),
                        location=issue.location,
                    )
                )

        return FrameStream(stream_header, _frames(), issues=issues)

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        partial = CapabilityLevel.PARTIAL
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": FieldCapability(
                    level=full.level,
                    notes="Atomic-species labels resolve through QE's documented label rule "
                    "(decorated labels Fe1 → Fe, O_vac → O; each resolution recorded).",
                ),
                "atoms.positions": FieldCapability(
                    level=full.level,
                    notes="The declared per-block unit is read (the header site table declares "
                    "'positions (<unit> units)'; each step's ATOMIC_POSITIONS card declares its "
                    "unit inline) and converted at the boundary — never an assumed unit.",
                ),
                "atoms.masses": FieldCapability(
                    level=full.level,
                    notes="Declared atomic-species masses promote to atoms.masses "
                    "(present-with-value, P3).",
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=full.level,
                    notes="The initial cell is read from the 'crystal axes' block in units of "
                    "alat; each step's own CELL_PARAMETERS card (the vc-relax/vc-md form) "
                    "supplies that step's cell, else the running cell is reused.",
                ),
                "cell.pbc": FieldCapability(
                    level=partial,
                    notes="Always (T,T,T) by format definition; pw.x output carries no "
                    "explicit PBC.",
                ),
                "dynamics.forces": FieldCapability(
                    level=full.level,
                    notes="Ry/bohr → eV/Å (QE's forces act on the atoms, the canonical "
                    "convention; no sign flip). A step without a force block reads None (P3).",
                ),
                "electronic.total_energy": FieldCapability(
                    level=full.level,
                    notes="The '!    total energy' line (Ry) → eV via QE's RYTOEV "
                    "(13.605693122994), hand-pinned.",
                ),
                "electronic.stress": FieldCapability(
                    level=full.level,
                    notes="Computed from QE's native Ry/bohr³ 3×3 block (QE prints the full "
                    "tensor): QE is compression-positive, so the tensor is sign-flipped to "
                    "canonical tension-positive and converted by QE's own constants; the kbar "
                    "column is the within-file cross-check (D195). A step without a stress "
                    "block reads None (P3 — never a defaulted zero tensor).",
                ),
                "simulation.extra": FieldCapability(
                    level=partial,
                    notes="Declared program string (the PWSCF version banner) → "
                    "simulation.source_code.",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=partial,
                    notes="Recognized-but-unmapped diagnostics (the per-step 'total force' "
                    "scalar) carried as 'qe_pw_out:<name>' with the QEOUT_UNMAPPED_BLOCK_CARRIED "
                    "warning (P1).",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=partial,
                    notes="The verbatim declared species table rides 'qe_pw_out:atomic_species'.",
                ),
            },
            max_frames=None,  # a trajectory: unbounded step count
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="cartesian",
            lossy_notes=list(_LOSSY_NOTES),
        )


def _build_stream_header(header: _Header, filename: str | None) -> StreamHeader:
    """Assemble the object-level metadata from the eagerly-parsed header."""
    return StreamHeader(
        schema_version=SCHEMA_VERSION,
        provenance=build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system=coordinate_system(header.initial_positions_unit),
            source_units={
                "positions": header.initial_positions_unit,
                "lattice_vectors": "alat",
                "energy": "rydberg",
                "forces": "rydberg/bohr",
                "stress": "rydberg/bohr^3",
            },
            parse_notes=list(header.notes)
            + [
                _PBC_NOTE,
                energy_parse_note(),
                forces_parse_note(),
                source_code_parse_note(),
                step_cell_parse_note(),
                step_positions_parse_note(),
                stress_parse_note(),
                masses_parse_note(),
            ],
        ),
        # pw.x numbers its steps but declares no per-step time axis: absent, not invented (P3).
        trajectory=TrajectoryMetadata(timestep=None),
        simulation=SimulationMetadata(source_code=header.version, extra={}),
        custom_global={
            _ATOMIC_SPECIES_KEY: {
                label: [valence, mass, pseudo] for label, valence, mass, pseudo in header.species
            }
        },
    )


def make_qe_pw_out_parser() -> QePwOutParser:
    return QePwOutParser()
