"""Quantum ESPRESSO pw.x input parser (MASTER_SPEC Part 3 §3; v1.4 M50-S1).

The pw.x **input** file — the namelist + card grammar that defines a QE calculation. It is
the structural ground truth of the whole QE trilogy: the pw.x *output* parser (M52) must
agree with it, so the shared mapping core ``parsers/_qe`` (D189) is where QE's structural
conventions get pinned, and this reader feeds it (the ``_vasp`` precedent, D160).

    &CONTROL
       calculation = 'scf',
    /
    &SYSTEM
       ibrav = 0, nat = 2, ntyp = 2,
       celldm(1) = 7.56,
    /
    &ELECTRONS
    /
    ATOMIC_SPECIES
       Fe 55.845 fe.pbe.UPF
       O  15.999 o.pbe.UPF
    ATOMIC_POSITIONS {angstrom}
       Fe 0.0 0.0 0.0
       O  1.5 1.5 1.5
    CELL_PARAMETERS {angstrom}
       5.0 0.0 0.0
       0.0 5.0 0.0
       0.0 0.0 5.0

**M50-S1 scope (the explicit-cell path).** ``ibrav = 0`` with an explicit
``CELL_PARAMETERS`` block parses end to end; an ``ibrav ≠ 0`` input **refuses**
``QEIN_UNSUPPORTED_IBRAV`` — the Bravais-lattice expansion lands in M50-S2, and this
reader's stub is replaced by the real dispatch there. QE declares its per-card units in
the file (``{angstrom|bohr|alat|crystal}``), so every conversion is a deterministic
boundary mapping recorded in ``parse_notes`` — **never a scenario**: no
``ambiguous_units``/``ambiguous_*`` issue exists for a QE source (the VASP contrast of
v1.2, not the LAMMPS ambiguity of v1.3).

**Registered parser-only as a staging state** (the lammps_dump/lammps_data precedent,
D175/D180 — *not* the vasprun/OUTCAR permanent source-never-target seam, D159/D164): the
``qe_pw_in`` exporter is M51's deliverable, so this format shows read-only in the
Capability Matrix until then. M51 must add the paired exporter and close the staging state.

**S1 honesty on the ordinary axes:**

* **No parser defaulting (P3).** ``nat``/``ntyp`` are required ``&system`` facts (QE
  requires them); ``ATOMIC_POSITIONS`` is always required; ``CELL_PARAMETERS`` is required
  when ``ibrav = 0`` (the cell is never defaulted); a ``{alat}`` card with no resolvable
  ``celldm(1)``/``A`` refuses rather than assume QE's 1-Bohr default. The *unit* default —
  a bare ``ATOMIC_POSITIONS``/``CELL_PARAMETERS`` reads as ``alat`` per QE's documented
  convention — is a format-defined fact, applied and recorded in ``parse_notes``.
* **Species labels are plain element symbols in S1.** ``atoms.symbols`` is required and
  must hold valid element symbols, so S1 resolves labels that *are* element symbols
  (through ``schema.elements.normalize_symbol``) and refuses a decorated label (``Fe1``,
  ``O_vac``) naming that its resolution lands in M50-S3.
* **Nothing is dropped (P1).** The full ``ATOMIC_SPECIES`` table (masses + pseudopotential
  filenames), any namelist entries beyond the consumed ``&system`` facts, and any
  unrecognized card (``K_POINTS``, ``OCCUPATIONS``, ``CONSTRAINTS``, …) are carried
  verbatim in ``user_metadata.custom_global`` under ``qe_pw_in:`` keys — the carry-through
  routing rule (Part 2 §6.1) admits carried-through content without a warning; M50-S3 adds
  the ``QEIN_UNMAPPED_ENTRY_CARRIED`` warning, routes recognized simulation context to
  ``simulation.extra``, promotes masses to ``atoms.masses`` and pseudopotentials to
  ``qe:pseudopotentials``, and carries ``K_POINTS`` as structured custom data.
* **Encoding errors name their location** (the RF-A1 discipline): a decode failure reports
  the byte offset; a malformed namelist/card reports the line and the offending construct.

Format-prefixed codes (Part 3 §5): ``QEIN_EMPTY``, ``QEIN_MALFORMED_NAMELIST``,
``QEIN_MALFORMED_CARD``, and the ``QEIN_UNSUPPORTED_IBRAV`` stub (S1; real expansion in S2).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import BinaryIO, TypeAlias, cast

import numpy as np
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance, decode_text
from xtalate.parsers._qe import (
    alat_angstrom,
    coordinate_system,
    lattice_from_cell_parameters,
    pbc_note,
    positions_cartesian,
)
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    UserMetadata,
)
from xtalate.schema.elements import normalize_symbol
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

FORMAT_ID = "qe_pw_in"

# Issue codes (Part 3 §5).
_EMPTY = "QEIN_EMPTY"
_MALFORMED_NAMELIST = "QEIN_MALFORMED_NAMELIST"
_MALFORMED_CARD = "QEIN_MALFORMED_CARD"
_UNSUPPORTED_IBRAV = "QEIN_UNSUPPORTED_IBRAV"

#: The custom_global key the full ATOMIC_SPECIES table rides under in S1: the mass and
#: pseudopotential columns have no canonical home in this milestone and are **never
#: dropped** (P1). M50-S3 promotes masses → atoms.masses and pseudopotentials →
#: user_metadata.custom_global["qe:pseudopotentials"].
_ATOMIC_SPECIES_KEY = "qe_pw_in:atomic_species"
#: The custom_global key unconsumed namelist entries ride under (per-namelist dict), and
#: the key unrecognized cards ride under (list of {card, unit, lines}). M50-S3 routes
#: these under the Part 2 §6.1 carry-through rule with the QEIN_UNMAPPED_ENTRY_CARRIED
#: warning.
_NAMELISTS_KEY = "qe_pw_in:namelists"
_UNMAPPED_CARDS_KEY = "qe_pw_in:unmapped_cards"

#: The QE namelists a pw.x input may carry (S1 reads &system's facts; the rest parse for
#: grammar validation and ride the carry). ``fcp`` is the fixed-cell-potential namelist.
_NAMELIST_NAMES = frozenset({"control", "system", "electrons", "ions", "cell", "fcp"})

#: The cards this reader recognizes (the QE pw.x card vocabulary). ATOMIC_SPECIES /
#: ATOMIC_POSITIONS / CELL_PARAMETERS are read; the rest (K_POINTS, OCCUPATIONS,
#: CONSTRAINTS, ATOMIC_VELOCITIES, …) are recognized as cards and carried verbatim — the
#: S1 cut line, never silently dropped (P1).
_CARD_KEYWORDS = frozenset(
    {
        "ATOMIC_SPECIES",
        "ATOMIC_POSITIONS",
        "ATOMIC_VELOCITIES",
        "ATOMIC_FORCES",
        "ATOMIC_CHARGES",
        "CELL_PARAMETERS",
        "K_POINTS",
        "OCCUPATIONS",
        "CONSTRAINTS",
    }
)

#: The &system facts S1 consumes; everything else in &system (and every other namelist)
#: rides the carry.
_CONSUMED_SYSTEM_KEYS = frozenset({"ibrav", "nat", "ntyp", "celldm", "a"})

# A Fortran number: optional sign, digits with optional fraction, optional [eEdD] exponent.
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?$")
_NAMELIST_HEAD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: The value types a namelist can hold: numbers (int/float), quoted strings, and Fortran
#: logicals (bool) — the tokenizer produces exactly these, plus ``ident`` bare tokens (also
#: str). An indexed key (``celldm(1)``) stores a ``{index: value}`` dict under the bare key.
_NamelistValue: TypeAlias = int | float | str | bool
_NamelistEntry: TypeAlias = _NamelistValue | dict[int, _NamelistValue]


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


def _strip_comment(line: str) -> str:
    """Strip a QE comment: everything from ``!`` to end of line (QE's comment character)."""
    return line.split("!", 1)[0]


# --- Fortran namelist reader ---------------------------------------------------------


def _find_unquoted_slash(text: str) -> int | None:
    """Index of the first ``/`` outside a quoted string in ``text``, or ``None`` — the
    Fortran namelist terminator, which may sit mid-line (``&system ibrav=0 /``)."""
    quote: str | None = None
    for idx, ch in enumerate(text):
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "/":
            return idx
    return None


def _namelist_tokens(body: str) -> list[tuple[str, _NamelistValue]]:
    """Tokenize a namelist body into ``(kind, value)`` pairs: ``ident`` (lowercased later by
    the caller), ``number`` (int or float), ``string``, ``logical`` (bool), and the
    punctuation kinds ``eq``/``lparen``/``rparen``/``slash``. Commas and whitespace are
    separators. Raises ``ValueError`` naming the offending construct — the reader turns
    that into the QEIN_MALFORMED_NAMELIST contract with a location."""
    tokens: list[tuple[str, _NamelistValue]] = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch.isspace() or ch == ",":
            i += 1
        elif ch == "/":
            tokens.append(("slash", "/"))
            i += 1
        elif ch == "=":
            tokens.append(("eq", "="))
            i += 1
        elif ch == "(":
            tokens.append(("lparen", "("))
            i += 1
        elif ch == ")":
            tokens.append(("rparen", ")"))
            i += 1
        elif ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n and body[j] != quote:
                j += 1
            if j >= n:
                raise ValueError(f"unterminated string literal {body[i:]!r}")
            tokens.append(("string", body[i + 1 : j]))
            i = j + 1
        elif ch.isalpha() or ch == "_":
            j = i
            while j < n and (body[j].isalnum() or body[j] in "_."):
                j += 1
            word = body[i:j]
            low = word.lower()
            if low in (".true.", ".false."):
                tokens.append(("logical", low == ".true."))
            else:
                tokens.append(("ident", word))
            i = j
        elif ch.isdigit() or ch in "+-.":
            j = i + 1
            while j < n and (body[j].isalnum() or body[j] in "+-."):
                j += 1
            raw = body[i:j]
            if not _NUMBER_RE.match(raw):
                raise ValueError(f"invalid numeric value {raw!r}")
            text = raw.lower().replace("d", "e")
            if any(c in raw for c in ".eEdD"):
                tokens.append(("number", float(text)))
            else:
                tokens.append(("number", int(raw)))
            i = j
        else:
            raise ValueError(f"unexpected character {ch!r} in namelist body")
    return tokens


def _parse_namelist_entries(
    tokens: list[tuple[str, _NamelistValue]],
) -> dict[str, _NamelistEntry]:
    """The ``{key: value}`` map of one namelist from its token stream.

    Keys are lowercased (Fortran namelist names are case-insensitive); an indexed key
    (``celldm(1)``) stores ``{index: value}`` under the bare key, so ``celldm`` reads as a
    dict of index → value. A repeated scalar key, or a key given both scalar and indexed,
    is malformed — Fortran would reject it too. Raises ``ValueError`` on any violation.
    """
    entries: dict[str, _NamelistEntry] = {}
    pos, n = 0, len(tokens)
    while pos < n:
        kind, value = tokens[pos]
        if kind == "slash":
            break
        if kind != "ident":
            raise ValueError(f"expected a namelist variable name, found {value!r}")
        key = str(value).lower()
        pos += 1
        index: int | None = None
        if pos < n and tokens[pos][0] == "lparen":
            idx_kind, idx_value = tokens[pos + 1]
            if idx_kind != "number" or not isinstance(idx_value, int):
                raise ValueError(f"invalid array index for {key}")
            index = idx_value
            pos += 2
            if pos >= n or tokens[pos][0] != "rparen":
                raise ValueError(f"unterminated array index for {key}")
            pos += 1
        if pos >= n or tokens[pos][0] != "eq":
            raise ValueError(f"expected '=' after {key}")
        pos += 1
        if pos >= n or tokens[pos][0] in ("eq", "slash", "lparen", "rparen"):
            raise ValueError(f"missing value for {key}")
        vkind, vvalue = tokens[pos]
        pos += 1
        if index is not None:
            bucket = entries.setdefault(key, {})
            if not isinstance(bucket, dict):
                raise ValueError(f"{key} is given both scalar and indexed values")
            bucket[index] = vvalue
        else:
            if key in entries:
                raise ValueError(f"{key} is given twice")
            entries[key] = vvalue
    return entries


def _read_namelist(lines: Sequence[str], i: int) -> tuple[str, dict[str, _NamelistEntry], int]:
    """Parse one ``&NAME ... /`` block starting at ``lines[i]`` (the ``&`` line).

    Returns ``(name, entries, next_index)``. The body is everything after the name up to
    the first unquoted ``/``, which may span several lines; a namelist never terminated by
    ``/`` is malformed (QE behaves the same — the reader swallows until it can find the
    terminator). Raises the QEIN_MALFORMED_NAMELIST contract with a line location.
    """
    line = _strip_comment(lines[i]).strip()
    rest = line[1:]  # after '&'
    match = _NAMELIST_HEAD_RE.match(rest)
    if match is None:
        raise _error(
            _MALFORMED_NAMELIST,
            f"namelist line {line!r} declares no name after '&'",
            location=f"line {i + 1}",
        )
    name = match.group(0).lower()
    body = rest[match.end() :]
    i += 1
    while True:
        terminator = _find_unquoted_slash(body)
        if terminator is not None:
            body = body[:terminator]
            break
        if i >= len(lines):
            raise _error(
                _MALFORMED_NAMELIST,
                f"namelist &{name} is never terminated by '/'",
                location=f"line {i}",
            )
        body += "\n" + _strip_comment(lines[i])
        i += 1
    try:
        entries = _parse_namelist_entries(_namelist_tokens(body))
    except ValueError as exc:
        raise _error(
            _MALFORMED_NAMELIST,
            f"malformed &{name} namelist: {exc}",
            location=f"&{name}",
        ) from exc
    return name, entries, i


# --- card reader ---------------------------------------------------------------------


def _card_unit(rest: str) -> str | None:
    """The ``{unit}`` annotation on a card header line's remainder, or ``None``. QE writes
    the declared per-card unit in braces after the card name (``ATOMIC_POSITIONS
    {angstrom}``); a card without braces uses the format's documented default (alat for
    ATOMIC_POSITIONS/CELL_PARAMETERS), which the reader applies and records."""
    match = re.match(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", rest.strip())
    if match is None:
        return None
    return match.group(1).lower()


def _read_card_block(lines: Sequence[str], i: int) -> tuple[list[str], int]:
    """The data lines of the card starting just before ``lines[i]``: everything up to the
    next card-keyword line (or end of file). Blank lines inside a block are skipped."""
    block: list[str] = []
    while i < len(lines):
        line = _strip_comment(lines[i]).strip()
        if not line:
            i += 1
            continue
        first = line.split()[0]
        if first.upper() in _CARD_KEYWORDS:
            break
        block.append(line)
        i += 1
    return block, i


def _floats(tokens: Sequence[str], *, location: str, count: int, what: str) -> list[float]:
    if len(tokens) != count:
        raise _error(
            _MALFORMED_CARD,
            f"{what} line must carry {count} numeric values, found {len(tokens)}: "
            f"{' '.join(tokens)!r}",
            location=location,
        )
    try:
        return [float(t) for t in tokens]
    except ValueError:
        raise _error(
            _MALFORMED_CARD,
            f"{what} line must carry numeric values, found {' '.join(tokens)!r}",
            location=location,
        ) from None


def _parse_atomic_species(
    block: list[str], ntyp: int, *, location: str
) -> list[tuple[str, float, str]]:
    rows: list[tuple[str, float, str]] = []
    for line in block:
        tokens = line.split()
        if len(tokens) != 3:
            raise _error(
                _MALFORMED_CARD,
                f"ATOMIC_SPECIES line must be 'label mass pseudopotential', found {line!r}",
                location=location,
            )
        label, mass_token, pseudo = tokens
        try:
            mass = float(mass_token)
        except ValueError:
            raise _error(
                _MALFORMED_CARD,
                f"ATOMIC_SPECIES mass for {label!r} is not numeric: {mass_token!r}",
                location=location,
            ) from None
        rows.append((label, mass, pseudo))
    if len(rows) != ntyp:
        raise _error(
            _MALFORMED_CARD,
            f"ATOMIC_SPECIES declares {len(rows)} species but &system declares ntyp={ntyp}; "
            "the declared counts must agree (never defaulted, P3)",
            location=location,
        )
    return rows


def _parse_positions(
    block: list[str], nat: int, *, location: str
) -> list[tuple[str, float, float, float]]:
    rows: list[tuple[str, float, float, float]] = []
    for line in block:
        tokens = line.split()
        if len(tokens) != 4:
            raise _error(
                _MALFORMED_CARD,
                f"ATOMIC_POSITIONS line must be 'label x y z', found {line!r}",
                location=location,
            )
        label = tokens[0]
        try:
            xyz = (float(tokens[1]), float(tokens[2]), float(tokens[3]))
        except ValueError:
            raise _error(
                _MALFORMED_CARD,
                f"ATOMIC_POSITIONS position for {label!r} is not numeric: "
                f"{' '.join(tokens[1:4])!r}",
                location=location,
            ) from None
        rows.append((label, *xyz))
    if len(rows) != nat:
        raise _error(
            _MALFORMED_CARD,
            f"ATOMIC_POSITIONS declares {len(rows)} atoms but &system declares nat={nat}; "
            "the declared counts must agree (never defaulted, P3)",
            location=location,
        )
    return rows


def _parse_cell(block: list[str], *, location: str) -> list[list[float]]:
    if len(block) != 3:
        raise _error(
            _MALFORMED_CARD,
            f"CELL_PARAMETERS must carry exactly 3 lattice rows, found {len(block)}",
            location=location,
        )
    rows = [
        _floats(line.split(), location=location, count=3, what="CELL_PARAMETERS") for line in block
    ]
    return rows


def _jsonify_namelist(entries: dict[str, _NamelistEntry]) -> dict[str, JsonValue]:
    """A namelist entry map as JSON values for the verbatim carry (Part 2 §3.10).

    An indexed key (``celldm(1)``) is stored under a ``{index: value}`` dict; JSON has no
    integer keys, so the index becomes its string form — the values themselves are never
    altered, only the key spelling (a carried value, never a rewrite)."""
    out: dict[str, JsonValue] = {}
    for key, value in entries.items():
        if isinstance(value, dict):
            out[key] = {str(index): item for index, item in value.items()}
        else:
            out[key] = value
    return out


# --- the parser ----------------------------------------------------------------------


class QePwInParser(ParserPlugin):
    """Quantum ESPRESSO pw.x input reader (Part 3 §3; M50-S1)."""

    version = "0.1.0"

    def __init__(self) -> None:
        self.format_id = FORMAT_ID
        self.format_name = "Quantum ESPRESSO pw.x input"
        self.file_extensions = (".in",)  # a hint only, never authoritative

    # -- sniff ------------------------------------------------------------------------

    def sniff(self, head: bytes, filename: str | None) -> float:
        # Signature: a leading Fortran namelist (&control/&system/...) — the one thing no
        # other text format in the registry writes — plus, at full confidence, the
        # ATOMIC_POSITIONS card. 0.7 for the namelist alone: a bare &system opener is
        # already unambiguous (nothing else starts a file with a QE namelist).
        text = head.decode("utf-8", errors="replace")
        significant: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("!"):
                continue
            significant.append(stripped)
            if len(significant) >= 5:
                break
        score = 0.0
        for line in significant:
            if line.startswith("&"):
                match = _NAMELIST_HEAD_RE.match(line[1:].lstrip())
                if match is not None and match.group(0).lower() in _NAMELIST_NAMES:
                    score = 0.7
                    break
        if "ATOMIC_POSITIONS" in text:
            score = max(score, 1.0)
        return score

    # -- parse ------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        text = decode_text(stream.read(), format_id=FORMAT_ID)
        lines = text.splitlines()
        if not any(_strip_comment(line).strip() for line in lines):
            raise _error(
                _EMPTY,
                "file is empty; a pw.x input starts with a &NAMELIST block",
            )

        # --- namelists (all precede the cards in a pw.x input) ------------------------
        namelists: dict[str, dict[str, _NamelistEntry]] = {}
        i = 0
        while i < len(lines):
            line = _strip_comment(lines[i]).strip()
            if not line:
                i += 1
                continue
            if not line.startswith("&"):
                break  # first card line
            name, entries, i = _read_namelist(lines, i)
            if name not in _NAMELIST_NAMES:
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"&{name} is not a pw.x namelist "
                    f"(recognized: {', '.join(sorted(_NAMELIST_NAMES))})",
                    location=f"&{name}",
                )
            if name in namelists:
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"namelist &{name} is declared twice",
                    location=f"&{name}",
                )
            namelists[name] = entries

        system = namelists.get("system")
        if system is None:
            raise _error(
                _MALFORMED_NAMELIST,
                "a pw.x input requires a &system namelist (nat and ntyp are required facts)",
                location="&system",
            )

        def _int_fact(key: str) -> int:
            value = system.get(key)
            if value is None:
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"&system is missing the required {key} (a pw.x input must declare it)",
                    location="&system",
                )
            if not isinstance(value, int):
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"&system {key} must be an integer, found {value!r}",
                    location="&system",
                )
            return value

        nat = _int_fact("nat")
        ntyp = _int_fact("ntyp")
        if nat <= 0:
            raise _error(
                _MALFORMED_NAMELIST,
                f"&system nat must be a positive atom count, found {nat}",
                location="&system",
            )
        if ntyp <= 0:
            raise _error(
                _MALFORMED_NAMELIST,
                f"&system ntyp must be a positive species count, found {ntyp}",
                location="&system",
            )

        ibrav = system.get("ibrav")
        if ibrav is not None:
            if not isinstance(ibrav, int):
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"&system ibrav must be an integer, found {ibrav!r}",
                    location="&system",
                )
            if ibrav != 0:
                # S1 stub: the Bravais expansion is M50-S2's deliverable. The refusal is
                # deliberately NOT recoverable (no recovery scenario exists — the plan's
                # "recovery_hint noting S2" is carried in the message instead, because an
                # unmapped hint would corrupt the hint→scenario contract, Part 4 §3.3).
                raise _error(
                    _UNSUPPORTED_IBRAV,
                    f"ibrav = {ibrav} is not supported by qe_pw_in in this milestone: the "
                    "Bravais-lattice expansion (celldm/A,B,C → lattice vectors) lands in "
                    "M50-S2. Only an explicit cell (ibrav = 0 + CELL_PARAMETERS) parses "
                    "here — the lattice is never guessed",
                    location="&system",
                )
        else:
            ibrav = 0

        # --- cards --------------------------------------------------------------------
        species_rows: list[tuple[str, float, str]] | None = None
        position_rows: list[tuple[str, float, float, float]] | None = None
        positions_unit: str | None = None
        cell_rows: list[list[float]] | None = None
        cell_unit: str | None = None
        unmapped_cards: list[dict[str, JsonValue]] = []
        unmapped_notes: list[str] = []
        default_unit_notes: list[str] = []

        while i < len(lines):
            line = _strip_comment(lines[i]).strip()
            if not line:
                i += 1
                continue
            if line.startswith("&"):
                raise _error(
                    _MALFORMED_CARD,
                    f"unexpected namelist after the card section: {line!r}",
                    location=f"line {i + 1}",
                )
            tokens = line.split()
            keyword = tokens[0].upper()
            if keyword not in _CARD_KEYWORDS:
                raise _error(
                    _MALFORMED_CARD,
                    f"unexpected data line outside a card: {line!r}",
                    location=f"line {i + 1}",
                )
            rest = line[len(tokens[0]) :].strip()
            block, i = _read_card_block(lines, i + 1)
            location = f"line {i - len(block)}"
            if keyword == "ATOMIC_SPECIES":
                if species_rows is not None:
                    raise _error(
                        _MALFORMED_CARD, "ATOMIC_SPECIES is declared twice", location=location
                    )
                species_rows = _parse_atomic_species(block, ntyp, location=location)
            elif keyword == "ATOMIC_POSITIONS":
                if position_rows is not None:
                    raise _error(
                        _MALFORMED_CARD, "ATOMIC_POSITIONS is declared twice", location=location
                    )
                unit = _card_unit(rest)
                if unit is None:
                    unit = "alat"  # QE's documented default; recorded below
                    default_unit_notes.append(
                        "ATOMIC_POSITIONS declared no unit; read as alat per QE's "
                        "documented default."
                    )
                if unit not in ("angstrom", "bohr", "alat", "crystal"):
                    raise _error(
                        _MALFORMED_CARD,
                        f"ATOMIC_POSITIONS declares unsupported unit {unit!r} "
                        "(angstrom|bohr|alat|crystal)",
                        location=location,
                    )
                position_rows = _parse_positions(block, nat, location=location)
                positions_unit = unit
            elif keyword == "CELL_PARAMETERS":
                if cell_rows is not None:
                    raise _error(
                        _MALFORMED_CARD, "CELL_PARAMETERS is declared twice", location=location
                    )
                unit = _card_unit(rest)
                if unit is None:
                    unit = "alat"  # QE's documented default; recorded below
                    default_unit_notes.append(
                        "CELL_PARAMETERS declared no unit; read as alat per QE's "
                        "documented default."
                    )
                if unit not in ("angstrom", "bohr", "alat"):
                    raise _error(
                        _MALFORMED_CARD,
                        f"CELL_PARAMETERS declares unsupported unit {unit!r} (angstrom|bohr|alat)",
                        location=location,
                    )
                cell_rows = _parse_cell(block, location=location)
                cell_unit = unit
            else:
                unmapped_cards.append(
                    {"card": keyword, "unit": _card_unit(rest), "lines": list(block)}
                )
                unmapped_notes.append(
                    f"card {keyword} has no canonical mapping in this milestone; carried verbatim "
                    f"in user_metadata.custom_global[{_UNMAPPED_CARDS_KEY!r}] (M50-S3 routes it "
                    "under the Part 2 §6.1 carry-through rule)."
                )

        if species_rows is None:
            raise _error(
                _MALFORMED_CARD,
                "missing required card ATOMIC_SPECIES (species labels are required for "
                "atoms.symbols)",
                location="card section",
            )
        if position_rows is None or positions_unit is None:
            raise _error(
                _MALFORMED_CARD,
                "missing required card ATOMIC_POSITIONS (positions are required, never defaulted)",
                location="card section",
            )
        if ibrav == 0 and cell_rows is None:
            raise _error(
                _MALFORMED_CARD,
                "missing required card CELL_PARAMETERS: ibrav = 0 declares an explicit cell, "
                "and the lattice is never defaulted (P3)",
                location="card section",
            )
        assert cell_rows is not None and cell_unit is not None  # refused above

        # --- species labels -> symbols (S1: plain element labels only) -----------------
        species_labels = {label for label, _, _ in species_rows}
        symbols: list[str] = []
        for label, *_ in position_rows:
            if label not in species_labels:
                raise _error(
                    _MALFORMED_CARD,
                    f"ATOMIC_POSITIONS labels an atom {label!r} that ATOMIC_SPECIES does not "
                    f"declare (species: {', '.join(sorted(species_labels))})",
                    location="ATOMIC_POSITIONS",
                )
            symbol = normalize_symbol(label)
            if symbol is None:
                raise _error(
                    _MALFORMED_CARD,
                    f"species label {label!r} is not a plain element symbol; decorated-label "
                    "resolution (e.g. Fe1 → Fe) lands in M50-S3",
                    location="ATOMIC_SPECIES",
                )
            symbols.append(symbol)

        # --- per-card unit conversions (the deterministic boundary, recorded) ----------
        needs_alat = positions_unit == "alat" or cell_unit == "alat"
        alat: float | None = None
        alat_note: str | None = None
        if needs_alat:
            celldm1: float | None = None
            celldm_entry = system.get("celldm")
            if isinstance(celldm_entry, dict):
                celldm1_value = celldm_entry.get(1)
                if celldm1_value is not None and (
                    not isinstance(celldm1_value, (int, float)) or isinstance(celldm1_value, bool)
                ):
                    raise _error(
                        _MALFORMED_NAMELIST,
                        f"&system celldm(1) must be numeric, found {celldm1_value!r}",
                        location="&system",
                    )
                celldm1 = float(celldm1_value) if celldm1_value is not None else None
            a_value = system.get("a")
            if a_value is not None and (
                not isinstance(a_value, (int, float)) or isinstance(a_value, bool)
            ):
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"&system A must be numeric, found {a_value!r}",
                    location="&system",
                )
            alat, alat_note = alat_angstrom(
                celldm1=celldm1, a=float(a_value) if a_value is not None else None
            )
            if alat is None:
                raise _error(
                    _MALFORMED_CARD,
                    "an alat-relative card is declared but &system carries neither celldm(1) "
                    "nor A to resolve alat; refusing rather than assuming QE's 1-bohr default "
                    "(P3)",
                    location="&system",
                )

        try:
            lattice, cell_note = lattice_from_cell_parameters(
                np.asarray(cell_rows, dtype=float), cell_unit, alat=alat
            )
            raw_xyz = np.asarray([[x, y, z] for _, x, y, z in position_rows], dtype=float)
            cartesian, pos_note = positions_cartesian(
                raw_xyz, positions_unit, lattice=lattice, alat=alat
            )
        except ValueError as exc:
            raise _error(_MALFORMED_CARD, str(exc), location="card section") from exc

        # --- provenance (the conversions are never silent) ----------------------------
        parse_notes: list[str] = []
        parse_notes.extend(default_unit_notes)
        if alat_note is not None:
            parse_notes.append(alat_note)
        parse_notes.append(cell_note)
        parse_notes.append(pos_note)
        parse_notes.append(pbc_note())
        parse_notes.append(
            "ATOMIC_SPECIES labels resolve to element symbols; the mass and pseudopotential "
            f"columns are carried verbatim in user_metadata.custom_global[{_ATOMIC_SPECIES_KEY!r}] "
            "(masses promote to atoms.masses in M50-S3)."
        )
        parse_notes.extend(unmapped_notes)

        # --- carries (nothing is dropped, P1) -----------------------------------------
        custom_global: dict[str, JsonValue] = {
            _ATOMIC_SPECIES_KEY: {label: [mass, pseudo] for label, mass, pseudo in species_rows}
        }
        carried_namelists: dict[str, dict[str, JsonValue]] = {}
        for name, entries in namelists.items():
            if name == "system":
                remaining = {
                    key: value for key, value in entries.items() if key not in _CONSUMED_SYSTEM_KEYS
                }
                if remaining:
                    carried_namelists["system"] = _jsonify_namelist(remaining)
            elif entries:
                carried_namelists[name] = _jsonify_namelist(entries)
        if carried_namelists:
            # Recursive JsonValue aliases do not narrow on assignment; the nested dict is
            # structurally JsonValue (string keys, JSON scalars/values throughout).
            custom_global[_NAMELISTS_KEY] = cast(JsonValue, carried_namelists)
        if unmapped_cards:
            custom_global[_UNMAPPED_CARDS_KEY] = cast(JsonValue, unmapped_cards)

        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system=coordinate_system(positions_unit),
            source_units={"positions": positions_unit, "lattice_vectors": cell_unit},
            parse_notes=parse_notes,
        )
        canonical = CanonicalObject(
            frames=[
                Frame(
                    index=0,
                    atoms=AtomsBlock(symbols=symbols, positions=cartesian),
                    cell=Cell(lattice_vectors=lattice, pbc=(True, True, True)),
                )
            ],
            trajectory=None,  # a pw.x input is a single structure, no time axis (§3.2)
            # The input declares no program string; M50-S3 routes &control metadata.
            simulation=None,
            provenance=provenance,
            user_metadata=UserMetadata(custom_global=custom_global),
        )
        return ParseResult(canonical=canonical, issues=[])

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
                        "Plain element species labels resolve in M50-S1; decorated labels "
                        "(Fe1, O_vac) resolve from M50-S3."
                    ),
                ),
                "atoms.positions": full,
                "atoms.masses": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Declared in ATOMIC_SPECIES; carried verbatim in M50-S1, promoted "
                        "to atoms.masses in M50-S3."
                    ),
                ),
                "cell.lattice_vectors": full,
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Always (T,T,T) by format definition; a pw.x input carries no PBC.",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "The ATOMIC_SPECIES table, unconsumed namelist entries, and "
                        "unrecognized cards carried verbatim (never dropped, P1)."
                    ),
                ),
            },
            max_frames=1,
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="both",
            lossy_notes=[],
        )


def make_qe_pw_in_parser() -> QePwInParser:
    return QePwInParser()
