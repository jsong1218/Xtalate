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
  header. The real VASP 5.x/6.x intra-step order is ``in kB`` stress (and, for NpT, the step's
  ``direct lattice vectors`` block) *before* the table, and the ``FREE ENERGIE OF THE ION-ELECTRON
  SYSTEM`` summary carrying ``energy(sigma->0)`` *after* it (VASP computes and prints the forces,
  then the electronic-energy summary). So the stress/cell that precede a table are buffered for
  that table's step, the table is read, then the reader scans *forward* to the step's
  ``energy(sigma->0)`` — which lands before the next step's ``TOTAL-FORCE`` — and only then emits
  the frame. A table whose step carries no ``energy(sigma->0)`` at all is a ``ParseError`` (P3 —
  never a defaulted energy): ``OUTCAR_MISSING_BLOCK`` when another step plainly follows, or the
  recoverable ``OUTCAR_TRUNCATED`` when the file simply ends after the forces (a torn write).
* **Positions are Cartesian (Å)** — read from the ``POSITION … TOTAL-FORCE`` table columns as-is
  (``mode=\"cartesian\"``), never re-run through the fractional→Cartesian lattice multiply.
  vasprun.xml positions are direct (fractional); the two readers land the same Cartesian positions
  (the M43 cross-check pins it).
* **Energy** — ``electronic.total_energy`` maps ``energy(sigma->0)`` (VASP's energy extrapolated to
  zero smearing, the same physical quantity as vasprun.xml's ``e_0_energy`` — the core's
  ``TOTAL_ENERGY_TAG`` decision). The ``energy without entropy`` scalar on the same line is carried
  verbatim per frame (never dropped, **P1**; never substituted for the total energy).
* **Magnetic moments (M45-S1, D171)** — ``electronic.magnetic_moments`` maps the ``magnetization
  (x)`` table's per-ion ``tot`` column (collinear scalar μB, spin-up-positive). This is an
  **OUTCAR-only** artifact — vasprun.xml carries no per-ion magnetization block. Real VASP prints
  the per-ion ``total charge``/``magnetization (x)`` tables (LORBIT≥10) after the step's
  electronic convergence and *before* its ``POSITION … TOTAL-FORCE`` table — the same
  pre-table region as the ``in kB`` stress — so the block is read there and attached to the
  frame whose force table follows (ASE's OUTCAR chunk boundary is the step's final
  ``FREE ENERGIE`` summary, which the table precedes). A run without the block reads ``None``
  (correct absence, P3); a recognized-but-malformed block refuses
  (``OUTCAR_UNRECOGNIZED_LAYOUT``/``OUTCAR_INCONSISTENT_STEP``), never a partial parse or a
  defaulted zero (P3); the non-collinear ``(y)/(z)`` tables are carried verbatim (v1.2.1).
* **Per-step cells (NpT).** A step's own ``direct lattice vectors`` block (when present) supplies
  that step's cell; a step without one reuses the running cell — the fixed-cell form (vasprun's
  ``_StepState`` pattern).
* **``pbc = (T,T,T)``** by format definition, as a ``parse_notes`` entry.

**Error contract (Part 3 §5; D164 + D165).** ``OUTCAR_EMPTY`` (empty file or no ionic-step block
at all), ``OUTCAR_MISSING_BLOCK`` (an expected block — the species list, the initial lattice, the
``energy(sigma->0)`` line, the force table — is absent in an otherwise-recognized context: a
``ParseError``, never a defaulted field, P3), the warning ``OUTCAR_UNMAPPED_LINE_CARRIED`` (a
recognized-but-unmapped diagnostic scalar carried verbatim, P1), ``OUTCAR_UNRECOGNIZED_LAYOUT`` (no
parseable VASP version banner, or a banner for a major version outside the recognized 5.x/6.x set —
the layout is refused, never a partial parse, P1; D165), and ``OUTCAR_INCONSISTENT_STEP`` (a step's
``POSITION … TOTAL-FORCE`` table carries more atoms than the header declares — refused, never
silently truncated, P3; D165), and ``OUTCAR_TRUNCATED`` (a torn write mid-stream — the file ends
mid-step after the energy/stress lines, or inside the force table — raised with
``recovery_hint="truncate_at_last_valid_frame"`` and resolved by the shared
``truncate_corrupt_tail`` scenario, never silently dropped, P1/P4; D166).

**Version-drift discipline (S2, D165).** Block-locating keys off the stable anchor substrings
(``TOTAL-FORCE``, ``energy(sigma->0)``, ``in kB``, ``direct lattice vectors``, the ``vasp.<major>``
banner, ``ions per type``) and column-splits on whitespace (``str.split()``) — never fixed byte
columns, which is exactly the fragility the 5.x↔6.x whitespace/column/label drift exploits. The
version banner's **major** component is the layout-recognition discriminator: majors 5 and 6 are
recognized and read; any other major (or no banner) is refused as ``OUTCAR_UNRECOGNIZED_LAYOUT``
rather than best-effort partial-parsed — a silently wrong force block poisons a training set.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

import numpy as np

from xtalate.parsers._common import build_provenance
from xtalate.parsers._vasp import (
    build_cell,
    forces,
    magnetic_moments,
    magnetic_moments_parse_note,
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
#: The non-collinear (x)/(y)/(z) magnetization tables, carried verbatim per frame under this key
#: until v1.2.1 gives the vector moments a canonical shape (the scalar field cannot hold them).
_MAGMOM_VECTOR_KEY = "magnetization_vector"
#: The recoverable torn-tail hint (Part 4 §3.3): a run killed mid-write leaves the already-read
#: ionic steps as good science behind a corrupt tail, so the reader marks the error and the caller
#: chooses whether to keep the prefix.
_TRUNCATE_HINT = "truncate_at_last_valid_frame"

# A single float token, including VASP's exponent forms (-0.12345678E+02).
_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

#: The version banner (` vasp.6.3.2 08Feb23 …` / ` vasp.5.4.4 18May18 …`) — the first such line is
#: the declared program, and its **major** component (group 1) is the layout-recognition
#: discriminator (S2): only majors 5 and 6 are recognized; anything else is refused, never misread.
_VERSION_RE = re.compile(r"\bvasp\.(\d+)\.(\d+)")
#: The recognized VASP major layouts (S2, D165). A banner for any other major — or no banner at
#: all — is refused as ``OUTCAR_UNRECOGNIZED_LAYOUT``: the version-drift refusal discipline, never a
#: best-effort partial parse.
_RECOGNIZED_MAJORS = frozenset({5, 6})
#: POTCAR species symbols, from `VRHFIN =X:` (one per species, in declared order). The bare element
#: symbol is the reliable source — the POTCAR `TITEL`/`POTCAR:` titles can carry `_pv`/`_sv`
#: suffixes.
_VRHFIN_RE = re.compile(r"VRHFIN\s*=\s*([A-Za-z]{1,2})\s*:")
_IONS_PER_TYPE_RE = re.compile(r"ions\s+per\s+type\s*=\s*(.*)")
_NIONS_RE = re.compile(r"NIONS\s*=\s*(\d+)")
_SIGMA0_RE = re.compile(rf"energy\(sigma->0\)\s*=\s*({_FLOAT})")
_WO_ENTROPY_RE = re.compile(rf"energy\s+without\s+entropy\s*=\s*({_FLOAT})")
_STRESS_RE = re.compile(r"\bin\s+kB\b\s+(.*)")
#: The `magnetization (x)`/`(y)`/`(z)` table headers — the stable anchor for the per-ion moment
#: tables (D171). Only the collinear `(x)` table maps to the scalar field; `(y)`/`(z)` mark the
#: non-collinear vector form (v1.2.1).
_MAGMOM_HEADER_RE = re.compile(r"magnetization\s*\(([xyz])\)")
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
_MAGNETIC_MOMENTS_NOTE = magnetic_moments_parse_note()

_PARSE_NOTES = [
    _POSITIONS_NOTE,
    _PBC_NOTE,
    _ENERGY_NOTE,
    _SOURCE_CODE_NOTE,
    _CELL_NOTE,
    _STEP_CELL_NOTE,
    _STRESS_NOTE,
    _MAGNETIC_MOMENTS_NOTE,
]


def _error(
    code: str,
    message: str,
    *,
    location: str | None = None,
    hint: str | None = None,
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


def _read_lattice(lines: Iterator[str], *, where: str, hint: str | None = None) -> np.ndarray:
    """The 3×3 lattice from the three rows after a ``direct lattice vectors`` header line.

    VASP prints each row as 6 numbers — the direct vectors followed by the reciprocal ones — so the
    first three columns are the lattice rows a, b, c. A *per-step* (NpT) block torn mid-write is a
    recoverable torn tail (``hint`` set → ``OUTCAR_TRUNCATED``); the header's own block is not (no
    valid prefix to keep → ``OUTCAR_MISSING_BLOCK``).
    """
    code = "OUTCAR_TRUNCATED" if hint is not None else "OUTCAR_MISSING_BLOCK"
    rows: list[list[float]] = []
    for _k in range(3):
        line = next(lines, None)
        if line is None:
            raise _error(
                code,
                f"file ended inside the direct lattice vectors block ({where})",
                location=where,
                hint=hint,
            )
        parts = line.split()
        if len(parts) < 6:
            raise _error(
                code,
                f"lattice row has fewer than 6 components ({where}): {line.strip()!r}",
                location=where,
                hint=hint,
            )
        try:
            rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
        except ValueError as exc:
            raise _error(
                code,
                f"non-numeric lattice row ({where}): {line.strip()!r}",
                location=where,
                hint=hint,
            ) from exc
    return np.asarray(rows, dtype=float)


@dataclass
class _Header:
    """Everything parsed eagerly before the first ionic step: the declared program (with its
    recognized major layout), the per-atom symbols (hence the atom count), and the initial lattice
    that fixed-cell steps reuse."""

    version: str
    major: int
    symbols: list[str]
    n_atoms: int
    lattice: np.ndarray


def _header_n_atoms(nions: int | None, counts: list[int] | None) -> int:
    """The ion count needed to read a pre-table ``magnetization (x)`` block in the first step,
    before the header is finalized: the declared ``ions per type`` sum (authoritative) or ``NIONS``
    as a fallback. Both are printed in the static header, ahead of any ionic step, so at least one
    is known by the time a magnetization table appears; if neither is, the block cannot be sized
    and the file is refused rather than misread (P1)."""
    if counts:
        return sum(counts)
    if nions is not None:
        return nions
    raise _error(
        "OUTCAR_MISSING_BLOCK",
        "a magnetization table appears before the ion count (NIONS / 'ions per type') is known — "
        "the block cannot be sized, so the file is refused rather than misread (P1)",
        location="frame 0",
    )


def _finalize_header(
    version: str | None,
    major: int | None,
    species: list[str],
    counts: list[int] | None,
    nions: int | None,
    lattice: np.ndarray | None,
) -> _Header:
    """Validate the eagerly-scanned header and build the ``_Header``.

    The version banner is the layout-recognition discriminator (S2, D165): no parseable banner, or
    a banner for a major outside the recognized 5.x/6.x set, is refused as
    ``OUTCAR_UNRECOGNIZED_LAYOUT`` — never a partial parse (P1). A *recognized* header missing an
    expected block (no species list, no initial lattice) is a ``ParseError`` under the §5 contract,
    never a defaulted field (P3). ``NIONS`` is a cross-check against the species counts, not the
    source of the count (the symbols come from the declared species, so the count must match them).
    """
    if version is None or major is None:
        raise _error(
            "OUTCAR_UNRECOGNIZED_LAYOUT",
            "no parseable VASP version banner (vasp.<major>.<minor>) found before the first ionic "
            "step — the OUTCAR layout cannot be recognized, so the file is refused rather than "
            "misread (P1); a corpus contribution for the unrecognized layout is welcome",
        )
    if major not in _RECOGNIZED_MAJORS:
        raise _error(
            "OUTCAR_UNRECOGNIZED_LAYOUT",
            f"VASP {major}.x OUTCAR layout is not recognized (recognized majors: "
            f"{sorted(_RECOGNIZED_MAJORS)}) — refused rather than misread (P1); please contribute "
            "a fixture for this layout",
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
    return _Header(version=version, major=major, symbols=symbols, n_atoms=n_atoms, lattice=lattice)


@dataclass
class _PreTable:
    """The step fields that precede a ``POSITION … TOTAL-FORCE`` table in real VASP order: the
    ``in kB`` stress, the per-ion ``magnetization (x)`` moments (LORBIT≥10, D171) or the
    non-collinear vector carry, and (for NpT) the step's own cell, which is threaded separately.
    The ``energy(sigma->0)`` is *not* here — it follows the table and is read forward from it
    (``_read_step_energy``)."""

    stress: np.ndarray | None
    magmoms: np.ndarray | None = None
    magmom_carry: dict[str, Any] | None = None


def _read_header(
    lines: Iterator[str], issues: list[ParseIssue]
) -> tuple[_Header | None, _PreTable | None]:
    """Scan the header eagerly and stop at the first ``POSITION … TOTAL-FORCE`` header line.

    Returns ``(None, None)`` when the file ends with no ionic-step table **after** a recognized
    version banner (the caller raises ``OUTCAR_EMPTY`` — a recognized header with zero steps). A
    file that ends with no version banner at all is refused here as ``OUTCAR_UNRECOGNIZED_LAYOUT``
    (S2): it is not an OUTCAR layout the reader recognizes. In real VASP order the first step's
    ``in kB`` stress, its (LORBIT≥10) ``magnetization (x)`` table, and (NpT) own ``direct lattice
    vectors`` block appear *before* its table, so they are captured for the step loop; its
    ``energy(sigma->0)`` appears *after* the table and is read there, not here.
    """
    version: str | None = None
    major: int | None = None
    species: list[str] = []
    counts: list[int] | None = None
    nions: int | None = None
    lattice: np.ndarray | None = None
    pending_stress: np.ndarray | None = None
    magmoms: np.ndarray | None = None
    magmom_carry: dict[str, Any] | None = None
    saw_step_signal = False
    line: str | None = None
    while True:
        if line is None:
            line = next(lines, None)
        if line is None:
            break
        if "TOTAL-FORCE" in line:
            header = _finalize_header(version, major, species, counts, nions, lattice)
            return header, _PreTable(pending_stress, magmoms, magmom_carry)
        if version is None and "vasp." in line:
            match = _VERSION_RE.search(line)
            if match:
                version = line.strip()
                major = int(match.group(1))
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
        elif "magnetization (" in line:
            n_atoms = _header_n_atoms(nions, counts)
            magmoms, magmom_carry, line = _read_magnetization(line, lines, n_atoms, 0, issues)
            saw_step_signal = True
            continue
        elif "in kB" in line:
            pending_stress = _parse_stress(line, 0)
            saw_step_signal = True
        elif "energy(sigma->0)" in line:
            # In real VASP order the energy summary follows the table; an energy line seen before
            # any table means a step began (its summary was written) but its force table is absent
            # — a torn/mangled step with no frame to keep (handled at EOF just below).
            saw_step_signal = True
        line = None
    if saw_step_signal:
        # A step began (a stress or energy line) but no POSITION/TOTAL-FORCE table header was ever
        # read — a torn write with *no* complete step to keep, so it stays a plain refusal (the
        # xdatcar 'opening header running out' counterpart, not a recoverable torn tail).
        raise _error(
            "OUTCAR_MISSING_BLOCK",
            "file ends mid-step (a torn write) with step content but no POSITION/TOTAL-FORCE "
            "table (P3: never a partial frame)",
            location="frame 0",
        )
    if version is None:
        raise _error(
            "OUTCAR_UNRECOGNIZED_LAYOUT",
            "file ends with no VASP version banner and no ionic-step table — not a recognized "
            "OUTCAR layout; refusing rather than misreading it (P1)",
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


def _noncollinear_magmom_warning(location: str) -> ParseIssue:
    """The non-collinear vector-moment carry: the (x)/(y)/(z) tables have no canonical scalar
    home, so they are carried verbatim under ``outcar:magnetization_vector`` with a named
    warning — never mis-mapped into the scalar ``electronic.magnetic_moments`` array (v1.2.1)."""
    return ParseIssue(
        severity="warning",
        code="OUTCAR_UNMAPPED_LINE_CARRIED",
        message=(
            "non-collinear magnetization (the (x)/(y)/(z) tables) is a moment vector per ion, "
            "which the scalar electronic.magnetic_moments field cannot hold; carried verbatim in "
            f"user_metadata.custom_per_frame['{_CARRY_KEY_PREFIX}{_MAGMOM_VECTOR_KEY}'] "
            "(mapping deferred to v1.2.1)"
        ),
        location=location,
    )


def _read_magmom_rows(
    lines: Iterator[str], n_atoms: int, frame_index: int, axis: str
) -> list[list[float]]:
    """The ``n_atoms`` rows of one ``magnetization (<axis>)`` table (after its ``# of ion … tot``
    column header), returned as ``[ion, s, p, d, tot]`` rows — the trailing ``tot`` column is the
    per-ion scalar moment.

    A recognized-but-malformed block refuses rather than partial-parses (P3): a missing/foreign
    column header is ``OUTCAR_UNRECOGNIZED_LAYOUT``; a wrong row count or a non-numeric row is
    ``OUTCAR_INCONSISTENT_STEP`` — never a silent partial parse and never a defaulted zero.
    """
    header_line = _next_data_line(lines)
    if header_line is None:
        raise _error(
            "OUTCAR_UNRECOGNIZED_LAYOUT",
            f"ionic step {frame_index}: 'magnetization ({axis})' has no '# of ion … tot' column "
            "header — the block layout is not recognized (P1)",
            location=f"frame {frame_index}",
        )
    header_parts = header_line.split()
    if not header_parts or "ion" not in header_parts or header_parts[-1] != "tot":
        raise _error(
            "OUTCAR_UNRECOGNIZED_LAYOUT",
            f"ionic step {frame_index}: 'magnetization ({axis})' column header is not the "
            f"recognized '# of ion … tot' form: {header_line.strip()!r}",
            location=f"frame {frame_index}",
        )
    rows: list[list[float]] = []
    for a in range(n_atoms):
        line = _next_data_line(lines)
        if line is None:
            raise _error(
                "OUTCAR_INCONSISTENT_STEP",
                f"ionic step {frame_index}: the 'magnetization ({axis})' table ended after {a} "
                f"of the declared {n_atoms} ions — refused, never a partial parse (P3)",
                location=f"frame {frame_index}",
            )
        if line.startswith("tot") or line.startswith("#"):
            raise _error(
                "OUTCAR_INCONSISTENT_STEP",
                f"ionic step {frame_index}: the 'magnetization ({axis})' table carries fewer "
                f"than the declared {n_atoms} ion rows (its terminator arrived after {a})",
                location=f"frame {frame_index}",
            )
        parts = line.split()
        if len(parts) < 5:
            raise _error(
                "OUTCAR_INCONSISTENT_STEP",
                f"ionic step {frame_index}: magnetization row {a + 1} has {len(parts)} "
                f"components, expected at least 5 (ion s p d tot): {line.strip()!r}",
                location=f"frame {frame_index}",
            )
        try:
            rows.append([float(p) for p in parts])
        except ValueError as exc:
            raise _error(
                "OUTCAR_INCONSISTENT_STEP",
                f"ionic step {frame_index}: non-numeric magnetization row: {line.strip()!r}",
                location=f"frame {frame_index}",
            ) from exc
    after = _next_nonblank_raw(lines)
    if after is not None and not _SEPARATOR_RE.match(after):
        parts = after.split()
        try:
            numeric = [float(p) for p in parts]
        except ValueError:
            numeric = []
        if len(numeric) >= 5:
            raise _error(
                "OUTCAR_INCONSISTENT_STEP",
                f"ionic step {frame_index}: the 'magnetization ({axis})' table has more than "
                f"the declared {n_atoms} ions (an extra row); refused, never silently truncated "
                "(P3)",
                location=f"frame {frame_index}",
            )
    return rows


def _read_magnetization(
    first_header: str,
    lines: Iterator[str],
    n_atoms: int,
    frame_index: int,
    issues: list[ParseIssue],
) -> tuple[np.ndarray | None, dict[str, Any] | None, str | None]:
    """The magnetization block(s), read from an already-consumed ``magnetization (x)`` header.

    In real VASP the per-ion ``magnetization (x)`` table (LORBIT≥10) is printed after the step's
    electronic convergence and *before* its ``POSITION … TOTAL-FORCE`` table — so this is called
    from the step's **pre-table** scan (``_scan_to_next_table``/``_read_header``), alongside the
    ``in kB`` stress, and the result is attached to the frame whose force table follows (D171).

    Returns ``(moments, carry, stop_line)``:

    * **collinear** (only ``magnetization (x)``): ``moments`` is the per-ion ``tot`` column
      mapped to canonical μB; ``carry`` is ``None``.
    * **non-collinear** (``(x)``+``(y)``+``(z)``): ``moments`` is ``None``; the three tables are
      carried verbatim in ``carry`` (under ``outcar:magnetization_vector``) with a named warning
      — never mapped into the scalar field (v1.2.1).

    ``stop_line`` is the first line consumed that is not part of the block — the block terminator
    the caller must reprocess (e.g. ``average (electrostatic) potential at core``, ``in kB``,
    ``direct lattice vectors``, or the next ``TOTAL-FORCE`` header), or ``None`` at end-of-file or
    after a ``(z)`` table. It is handed back, never dropped.
    """
    axes: list[str] = []
    rows_by_axis: dict[str, list[list[float]]] = {}
    stop_line: str | None = None
    pending: str | None = first_header
    while pending is not None:
        match = _MAGMOM_HEADER_RE.search(pending)
        if match is None:
            raise _error(
                "OUTCAR_UNRECOGNIZED_LAYOUT",
                f"ionic step {frame_index}: unrecognized magnetization table header "
                f"{pending.strip()!r} (expected 'magnetization (x)' and optionally (y)/(z))",
                location=f"frame {frame_index}",
            )
        axis = match.group(1)
        expected = "x" if not axes else ("y" if axes == ["x"] else "z")
        if axis != expected or len(axes) >= 3:
            raise _error(
                "OUTCAR_UNRECOGNIZED_LAYOUT",
                f"ionic step {frame_index}: magnetization table axes out of order "
                f"({axes} then {axis!r}; expected {expected!r})",
                location=f"frame {frame_index}",
            )
        rows_by_axis[axis] = _read_magmom_rows(lines, n_atoms, frame_index, axis)
        axes.append(axis)
        if axis == "z":
            break
        # Peek past the table's ``tot`` summary and separators to the next meaningful line: either
        # the next magnetization axis (non-collinear), or the block terminator to hand back. The
        # per-axis ``_read_magmom_rows`` consumes only the rows and their closing rule, not the
        # trailing ``tot  …`` summary line, so skip that here before deciding.
        nxt = _next_data_line(lines)
        while nxt is not None and nxt.lstrip().startswith("tot"):
            nxt = _next_data_line(lines)
        if nxt is not None and "magnetization (" in nxt:
            pending = nxt
            continue
        stop_line = nxt
        pending = None
    if axes == ["x"]:
        return magnetic_moments([row[-1] for row in rows_by_axis["x"]]), None, stop_line
    if axes == ["x", "y"]:
        raise _error(
            "OUTCAR_INCONSISTENT_STEP",
            f"ionic step {frame_index}: non-collinear magnetization has (x)/(y) tables but no "
            "(z) table — refused, never a partial vector (P3)",
            location=f"frame {frame_index}",
        )
    carry = {
        f"{_CARRY_KEY_PREFIX}{_MAGMOM_VECTOR_KEY}": [
            rows_by_axis["x"],
            rows_by_axis["y"],
            rows_by_axis["z"],
        ]
    }
    issues.append(_noncollinear_magmom_warning(f"frame {frame_index}"))
    return None, carry, stop_line


def _next_data_line(lines: Iterator[str]) -> str | None:
    """The next non-blank, non-dash-separator line — VASP frames its tables with ``---…`` rules."""
    for line in lines:
        if line.strip() and not _SEPARATOR_RE.match(line):
            return line
    return None


def _next_nonblank_raw(lines: Iterator[str]) -> str | None:
    """The next non-blank line, **not** skipping dash separators.

    The peek that lets the force-table reader tell a terminating ``---`` rule from a stray extra
    row — ``_next_data_line`` would skip the separator and hide the boundary.
    """
    for line in lines:
        if line.strip():
            return line
    return None


def _read_force_rows(
    lines: Iterator[str], n_atoms: int, frame_index: int
) -> tuple[np.ndarray, str | None]:
    """The ``n_atoms`` rows of the ``POSITION … TOTAL-FORCE`` table (``x y z fx fy fz``).

    A block that ends before its rows complete, or a row that is not 6 numeric components, is a
    **recoverable** ``ParseError`` — ``OUTCAR_TRUNCATED`` with
    ``recovery_hint="truncate_at_last_valid_frame"`` (a run killed mid-write) — never a silently
    shortened table (P2) and never a defaulted force (P3). After the declared ``n_atoms`` rows the
    table must terminate (a ``---`` rule or end-of-file); a further 6-component row means the table
    carries **more atoms than the header declares** — a structural inconsistency refused as
    ``OUTCAR_INCONSISTENT_STEP`` (S2), never silently truncated to the shorter (P3).

    Returns ``(rows, handback)``: ``handback`` is a consumed non-terminator, non-row line the caller
    must reprocess (the only way to peek without a pushback stream); it is ``None`` on the normal
    terminator path.
    """
    rows: list[list[float]] = []
    for a in range(n_atoms):
        line = _next_data_line(lines)
        if line is None:
            raise _error(
                "OUTCAR_TRUNCATED",
                f"ionic step {frame_index}: the POSITION/TOTAL-FORCE table ended after {a} of "
                f"{n_atoms} atoms — the file appears truncated mid-table",
                location=f"frame {frame_index}",
                hint=_TRUNCATE_HINT,
            )
        parts = line.split()
        if len(parts) != 6:
            raise _error(
                "OUTCAR_TRUNCATED",
                f"ionic step {frame_index}: force row {a + 1} has {len(parts)} components, "
                f"expected 6 (x y z fx fy fz): {line.strip()!r}",
                location=f"frame {frame_index}",
                hint=_TRUNCATE_HINT,
            )
        try:
            rows.append([float(p) for p in parts])
        except ValueError as exc:
            raise _error(
                "OUTCAR_TRUNCATED",
                f"ionic step {frame_index}: non-numeric force row: {line.strip()!r}",
                location=f"frame {frame_index}",
                hint=_TRUNCATE_HINT,
            ) from exc
    after = _next_nonblank_raw(lines)
    if after is None or _SEPARATOR_RE.match(after):
        return np.asarray(rows, dtype=float), None
    parts = after.split()
    if len(parts) == 6:
        try:
            [float(p) for p in parts]
        except ValueError:
            pass
        else:
            raise _error(
                "OUTCAR_INCONSISTENT_STEP",
                f"ionic step {frame_index}: the POSITION/TOTAL-FORCE table has more than the "
                f"declared {n_atoms} atoms (an extra 6-component row); a structural inconsistency "
                "is refused, never silently truncated (P3)",
                location=f"frame {frame_index}",
            )
    return np.asarray(rows, dtype=float), after


def _build_frame(
    header: _Header,
    rows: np.ndarray,
    lattice: np.ndarray,
    energy: float,
    carry: float | None,
    stress: np.ndarray | None,
    magmoms: np.ndarray | None,
    magmom_carry: dict[str, Any] | None,
    issues: list[ParseIssue],
    frame_index: int,
) -> StreamFrame:
    """Build one frame from the parsed force rows, the step's pending energy/stress, and the
    step's (optional) magnetization block."""
    frame = Frame(
        index=frame_index,
        atoms=AtomsBlock(
            symbols=list(header.symbols),
            positions=positions(rows[:, :3], lattice, mode="cartesian"),
        ),
        cell=build_cell(lattice),
        dynamics=Dynamics(forces=forces(rows[:, 3:])),
        electronic=Electronic(
            total_energy=total_energy(energy),
            stress=stress,
            magnetic_moments=magmoms,
        ),
    )
    per_frame_custom: dict[str, Any] = {}
    if carry is not None:
        key = f"{_CARRY_KEY_PREFIX}{_ENERGY_WO_ENTROPY_KEY}"
        per_frame_custom[key] = carry
        issues.append(_carry_warning(_ENERGY_WO_ENTROPY_KEY, location=f"frame {frame_index}"))
    if magmom_carry is not None:
        per_frame_custom.update(magmom_carry)
    return StreamFrame(frame=frame, per_frame_custom=per_frame_custom)


def _read_step_energy(
    lines: Iterator[str],
    frame_index: int,
    first_line: str | None,
) -> tuple[float | None, float | None, bool]:
    """Scan forward from just past a step's force table to that step's ``energy(sigma->0)``.

    Real VASP prints the ``FREE ENERGIE OF THE ION-ELECTRON SYSTEM`` summary (carrying
    ``energy(sigma->0)``) *after* the ``POSITION … TOTAL-FORCE`` table and before the next step
    begins, so this reads forward from the table. Returns ``(energy, carry, hit_next_table)``:

    * ``(energy, carry, False)`` once the step's ``energy(sigma->0)`` is found — the common path,
      returning *before* the next step's stress/cell/magnetization so those stay for
      ``_scan_to_next_table``;
    * ``(None, None, True)`` if the next step's ``TOTAL-FORCE`` table is reached first — the step
      has a force table but no energy summary though the file continues (the caller raises
      ``OUTCAR_MISSING_BLOCK`` — never a defaulted energy, P3);
    * ``(None, None, False)`` at end-of-file with no energy — a torn write after the forces (the
      caller raises the recoverable ``OUTCAR_TRUNCATED``).

    ``first_line`` is the peeked line the force-table reader handed back (usually ``None``).
    """
    line = first_line
    while True:
        if line is None:
            line = next(lines, None)
        if line is None:
            return None, None, False
        if "TOTAL-FORCE" in line:
            return None, None, True
        if "energy(sigma->0)" in line:
            energy, carry = _parse_energy_line(line, frame_index)
            return energy, carry, False
        line = None


def _scan_to_next_table(
    lines: Iterator[str],
    lattice: np.ndarray,
    next_frame_index: int,
    n_atoms: int,
    issues: list[ParseIssue],
) -> tuple[_PreTable, np.ndarray, bool]:
    """Scan from just past a step's energy summary to the next step's ``TOTAL-FORCE`` header,
    capturing that next step's pre-table ``in kB`` stress, its (LORBIT≥10) ``magnetization (x)``
    moments, and (NpT) own ``direct lattice vectors`` cell along the way.

    Returns ``(pre_table, lattice, found)``; ``found`` is ``False`` at end-of-file (no further
    step). A ``direct lattice vectors`` block torn mid-write here is a recoverable torn tail
    (``OUTCAR_TRUNCATED``): the current frame has already been emitted, so truncate-mode keeps it.
    In real VASP order the per-ion ``magnetization (x)`` table (D171) precedes the force table, so
    it is read here and attached to the *next* frame — the same pre-table region as the stress.
    """
    pending_stress: np.ndarray | None = None
    magmoms: np.ndarray | None = None
    magmom_carry: dict[str, Any] | None = None
    line: str | None = None
    while True:
        if line is None:
            line = next(lines, None)
        if line is None:
            return _PreTable(pending_stress, magmoms, magmom_carry), lattice, False
        if "TOTAL-FORCE" in line:
            return _PreTable(pending_stress, magmoms, magmom_carry), lattice, True
        if "magnetization (" in line:
            magmoms, magmom_carry, line = _read_magnetization(
                line, lines, n_atoms, next_frame_index, issues
            )
            continue
        if "in kB" in line:
            pending_stress = _parse_stress(line, next_frame_index)
        elif "direct lattice vectors" in line:
            lattice = _read_lattice(lines, where=f"frame {next_frame_index}", hint=_TRUNCATE_HINT)
        line = None


def _steps(
    lines: Iterator[str],
    header: _Header,
    first_pre: _PreTable,
    issues: list[ParseIssue],
) -> Iterator[StreamFrame]:
    """Yield one ``StreamFrame`` per ``POSITION … TOTAL-FORCE`` table, lazily, one step resident.

    Real VASP order per step: the pre-table stress/cell/magnetization (``pre``), the force table,
    then the ``energy(sigma->0)`` summary. Each frame is emitted only once its own energy is read —
    the energy is *never* borrowed from a neighbouring step, and its per-ion moments come from the
    pre-table region that precedes its force table (D171).
    """
    lattice = header.lattice
    pre = first_pre
    frame_index = 0
    while True:
        rows, handback = _read_force_rows(lines, header.n_atoms, frame_index)
        energy, carry, hit_next_table = _read_step_energy(lines, frame_index, handback)
        if energy is None:
            if hit_next_table:
                raise _error(
                    "OUTCAR_MISSING_BLOCK",
                    f"ionic step {frame_index}: the POSITION/TOTAL-FORCE table has no following "
                    "energy(sigma->0) summary before the next step (P3: never a defaulted energy)",
                    location=f"frame {frame_index}",
                )
            raise _error(
                "OUTCAR_TRUNCATED",
                f"ionic step {frame_index}: file ends after the force table with no "
                "energy(sigma->0) summary — the file appears truncated after the forces",
                location=f"frame {frame_index}",
                hint=_TRUNCATE_HINT,
            )
        yield _build_frame(
            header,
            rows,
            lattice,
            energy,
            carry,
            pre.stress,
            pre.magmoms,
            pre.magmom_carry,
            issues,
            frame_index,
        )
        frame_index += 1
        pre, lattice, found = _scan_to_next_table(
            lines, lattice, frame_index, header.n_atoms, issues
        )
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

    def parse_recover(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
    ) -> ParseResult:
        """Recover an OUTCAR whose tail is a torn write by keeping the valid prefix
        (``truncate_at_last_valid_frame`` → ``truncate``, Part 4 §3.3; v1.2 M43-S3, D166).

        The characteristic OUTCAR failure: a run killed while writing ionic step *k*, so steps
        0..k-1 are perfectly good science behind a corrupt tail. Only ``truncate`` reaches here —
        ``abort`` is the caller declining to recover, handled in the orchestration
        (``conversion.parse_recovery``) — and only the ``truncate_at_last_valid_frame`` hint is
        handled. Re-reads through the *same* streaming path in truncate mode, so the kept prefix is
        read by exactly the code that reads an intact file, and the truncation is recorded as a
        warning ``ParseIssue`` — the dropped tail is never silent (P1).
        """
        if hint != _TRUNCATE_HINT:
            raise NotImplementedError(f"outcar parse_recover does not handle hint {hint!r}")
        if choice != "truncate":
            raise NotImplementedError(
                f"outcar parse_recover applies only the 'truncate' choice (got {choice!r})"
            )
        frame_stream = self.parse_stream(stream, filename=filename, truncate=True)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def parse_stream(
        self, stream: BinaryIO, *, filename: str | None, truncate: bool = False
    ) -> FrameStream:
        """Header-eager, step-lazy OUTCAR parse (M43-S1/S3; Part 3 §2).

        ``truncate`` is the internal switch ``parse_recover`` sets to apply the caller's
        ``truncate_at_last_valid_frame`` choice: a recoverable error mid-stream then *ends* the
        stream at the last good step (recording an ``OUTCAR_TRUNCATED`` warning) instead of
        propagating. It is not part of the ``ParserPlugin.parse_stream`` contract — callers reach it
        through ``parse_recover``, so the default read stays the honest one that refuses a corrupt
        file.
        """
        head = stream.read(4096)
        if not head.strip():
            raise _error("OUTCAR_EMPTY", "file is empty")
        stream.seek(0)
        lines = _line_reader(stream)
        issues: list[ParseIssue] = []
        header, first_pre = _read_header(lines, issues)
        if header is None or first_pre is None:
            raise _error(
                "OUTCAR_EMPTY",
                "file contains no ionic-step block (no POSITION/TOTAL-FORCE table)",
            )
        stream_header = _build_stream_header(header, filename)

        def _frames() -> Iterator[StreamFrame]:
            yielded = 0
            try:
                for frame in _steps(lines, header, first_pre, issues):
                    yielded += 1
                    yield frame
            except ParseError as exc:
                # Truncate mode: a *recoverable* mid-stream error ends the stream at the last good
                # step instead of propagating. Two guards keep this honest: only errors the parser
                # itself marked recoverable are swallowed — a structurally wrong file (an
                # OUTCAR_INCONSISTENT_STEP) still raises, because that is not a torn tail — and the
                # truncation is recorded as a warning so the dropped tail is never silent (P1).
                issue = exc.issues[0]
                if not (truncate and issue.recovery_hint == _TRUNCATE_HINT):
                    raise
                if yielded == 0:
                    # Truncating to nothing is not a recovery: there is no valid prefix to keep, so
                    # the honest answer is the original error — never an empty frame list that would
                    # escape the §5 contract into a raw pydantic error.
                    raise
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="OUTCAR_TRUNCATED",
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
                "electronic.magnetic_moments": FieldCapability(
                    level=full.level,
                    notes="Collinear per-ion μB moments read from the 'magnetization (x)' "
                    "table's 'tot' column (spin-up-positive, verbatim — D171). An OUTCAR-only "
                    "artifact: vasprun.xml carries no per-ion magnetization block. A run "
                    "without a magnetization block reads None (P3); the non-collinear (y)/(z) "
                    "tables are carried verbatim, not mapped (v1.2.1).",
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
