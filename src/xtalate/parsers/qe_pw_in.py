"""Quantum ESPRESSO pw.x input parser (MASTER_SPEC Part 3 §3; v1.4 M50-S1/S2/S3).

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

**M50-S1 scope (the explicit-cell path) + M50-S2 (the ``ibrav`` expansion).** ``ibrav =
0`` with an explicit ``CELL_PARAMETERS`` block parses end to end (S1); ``ibrav ≠ 0`` in
the hand-pinned supported set (``1, 2, 3, 4, 6, 8, 12, -12, 14``) expands to
``cell.lattice_vectors`` via the shared ``_qe`` core (S2, D190), the derivation recorded
in ``parse_notes``. An ``ibrav`` outside the supported set **refuses**
``QEIN_UNSUPPORTED_IBRAV`` naming the value — the set grows by corpus evidence (M53),
and the lattice is never guessed (P4). ``CELL_PARAMETERS`` alongside ``ibrav ≠ 0`` is a
QE contradiction and **refuses** ``QEIN_MALFORMED_CARD`` naming the conflict (D190 — a
silent preference between two disagreeing sources is the rejected alternative). QE
declares its per-card units in the file (``{angstrom|bohr|alat|crystal}``), so every
conversion is a deterministic boundary mapping recorded in ``parse_notes`` — **never a
scenario**: no ``ambiguous_units``/``ambiguous_*`` issue exists for a QE source (the
VASP contrast of v1.2, not the LAMMPS ambiguity of v1.3).

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
* **Species labels resolve through QE's documented label rule (M50-S3, D191).**
  ``atoms.symbols`` is required, so ``ATOMIC_SPECIES`` labels resolve to elements via the
  shared ``_qe`` core's ``species_symbol`` (QE's rule: the element is the leading 1–2
  characters that form an element symbol — ``Fe1`` → Fe, ``O_vac`` → O, tried as
  ``normalize_symbol`` over the label, never guessed), each resolution recorded in
  ``parse_notes``. A label whose leading characters form **no** element refuses
  ``QEIN_UNRESOLVED_SPECIES_LABEL`` with the ``supply_species`` recovery hint (the
  **existing** ``missing_species`` scenario, Part 4 §3.3 — no QE-specific recovery is
  invented, D191): ``--recover missing_species=species_map=…`` or ``upload_reference``
  re-reads and completes, recorded with the ``QEIN_SPECIES_SUPPLIED`` warning.
* **Masses are present-with-value (P3, D191).** Declared ``ATOMIC_SPECIES`` masses promote
  to ``atoms.masses`` — a declared value is never a fabricated default, and absence stays
  ``None``. Pseudopotential filenames land under
  ``user_metadata.custom_global["qe:pseudopotentials"]`` (label → filename) and the full
  declared table still rides ``qe_pw_in:atomic_species`` verbatim.
* **Nothing is dropped (P1).** Any namelist entry beyond the consumed structural facts and
  the recognized simulation context, and any unrecognized card (``K_POINTS``,
  ``OCCUPATIONS``, ``CONSTRAINTS``, …) is carried verbatim in ``user_metadata.custom_global``
  under ``qe_pw_in:`` keys — the carry-through routing rule (Part 2 §6.1) — and **each**
  carried item emits the ``QEIN_UNMAPPED_ENTRY_CARRIED`` **warning** (kept + reported,
  never refused). Recognized simulation context (``calculation``, cutoffs/convergence:
  ``ecutwfc``/``ecutrho``/``conv_thr``/``degauss``/``smearing``/``occupations``) routes to
  ``simulation.extra`` (the vasprun precedent). ``K_POINTS`` is carried verbatim as
  structured custom data — the schema has no canonical k-point model, and M50-S3 states
  that rather than inventing one.
* **Encoding errors name their location** (the RF-A1 discipline): a decode failure reports
  the byte offset; a malformed namelist/card reports the line and the offending construct.

Format-prefixed codes (Part 3 §5): ``QEIN_EMPTY``, ``QEIN_MALFORMED_NAMELIST``,
``QEIN_MALFORMED_CARD``, ``QEIN_UNSUPPORTED_IBRAV`` (an ``ibrav`` outside the
hand-pinned supported set), ``QEIN_UNRESOLVED_SPECIES_LABEL`` (an ``ATOMIC_SPECIES``
label no element — recoverable through the existing ``missing_species`` scenario),
``QEIN_UNMAPPED_ENTRY_CARRIED`` (a carried-through namelist entry / unrecognized card —
warning, never a refusal), and ``QEIN_SPECIES_SUPPLIED`` (the recovery-completion note
when a species_map / upload_reference completes the read).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import BinaryIO, TypeAlias, cast

import numpy as np
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance, decode_text
from xtalate.parsers._qe import (
    UnsupportedIbravError,
    alat_angstrom,
    coordinate_system,
    lattice_from_cell_parameters,
    lattice_from_ibrav,
    pbc_note,
    positions_cartesian,
    species_symbol,
)
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Frame,
    SimulationMetadata,
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
from xtalate.sdk.qe import (
    _ATOMIC_SPECIES_KEY,
    _CONSUMED_SYSTEM_KEYS,
    _NAMELISTS_KEY,
    _PSEUDOPOTENTIALS_KEY,
    _SIMULATION_EXTRA_KEYS,
    _UNMAPPED_CARDS_KEY,
)

FORMAT_ID = "qe_pw_in"

# Issue codes (Part 3 §5).
_EMPTY = "QEIN_EMPTY"
_MALFORMED_NAMELIST = "QEIN_MALFORMED_NAMELIST"
_MALFORMED_CARD = "QEIN_MALFORMED_CARD"
_UNSUPPORTED_IBRAV = "QEIN_UNSUPPORTED_IBRAV"
_UNRESOLVED_SPECIES_LABEL = "QEIN_UNRESOLVED_SPECIES_LABEL"
_UNMAPPED_ENTRY_CARRIED = "QEIN_UNMAPPED_ENTRY_CARRIED"
_SPECIES_SUPPLIED = "QEIN_SPECIES_SUPPLIED"

#: The recovery hint of the shared ``missing_species`` scenario (Part 4 §3.3), the same
#: hint the LAMMPS parsers raise — the hazard is identical, so it is one scenario reused,
#: never a QE-specific recovery invented (D191).
_SPECIES_HINT = "supply_species"

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
            tokens.append(("ident", body[i:j]))
            i = j
        elif ch.isdigit() or ch in "+-.":
            j = i + 1
            while j < n and (body[j].isalnum() or body[j] in "+-."):
                j += 1
            raw = body[i:j]
            # Fortran logicals (.true./.false.) begin with '.', so they arrive here rather
            # than in the ident branch; recognize them before the numeric contract.
            low = raw.lower()
            if low in (".true.", ".false."):
                tokens.append(("logical", low == ".true."))
                i = j
                continue
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
    """The unit/option annotation on a card header line's remainder, or ``None`` when the
    remainder is empty. QE writes the per-card option after the card name in any of three
    interchangeable spellings — brace-wrapped (``ATOMIC_POSITIONS {angstrom}``),
    paren-wrapped (``ATOMIC_POSITIONS (angstrom)``), or bare (``ATOMIC_POSITIONS
    angstrom``) — and all three name the same option; the leading token is returned
    lowercased for whichever spelling is used (this is also how an unmapped card's mode,
    e.g. ``K_POINTS automatic``, is captured). Only a header with no remainder at all
    returns ``None``, which for ATOMIC_POSITIONS/CELL_PARAMETERS means QE's documented
    default (alat) applies — recorded by the caller."""
    match = re.match(r"[{(]?\s*([A-Za-z_][A-Za-z0-9_]*)", rest.strip())
    if match is None:
        return None
    return match.group(1).lower()


def _unmapped_card_lead(keyword: str) -> str:
    """The shared leading clause naming why a card carries verbatim, single-sourced for
    both the ``parse_notes`` entry and the QEIN_UNMAPPED_ENTRY_CARRIED warning so the two
    surfaces cannot drift."""
    if keyword == "K_POINTS":
        return (
            "card K_POINTS has no canonical k-point model in the schema (M50-S3 "
            "states that rather than inventing one); carried verbatim as structured "
            "custom data"
        )
    return f"card {keyword} has no canonical mapping in this milestone; carried verbatim"


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


# --- the missing_species recovery presets (Part 4 §3.3; D191) ---------------------------


def _recover_label_map(parameters: dict[str, object]) -> Mapping[str, str]:
    """Parse the ``species_map`` choice's ``species`` parameter for a QE source: a
    **label**→symbol mapping (QE species are names, not numeric types — the LAMMPS
    type→symbol shape does not apply, so an ordered list is honestly not accepted). A
    dict passes through with string keys; the CLI's string form (``"Fe1:Fe O_vac:O"`` —
    colon-delimited label:symbol pairs, space-separated, since commas are the
    ``--recover`` separator) is split into a mapping. Commas inside the string are
    tolerated too, so a direct API caller can pass ``"Fe1:Fe,O_vac:O"``. The values are
    resolved through ``normalize_symbol`` at use time — a non-element value is refused
    there, never guessed."""
    raw = parameters.get("species")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        tokens = raw.replace(":", " ").replace(",", " ").split()
        if len(tokens) == 0 or len(tokens) % 2 != 0:
            raise _error(
                _UNRESOLVED_SPECIES_LABEL,
                "species_map needs label:symbol pairs "
                f"(e.g. species='Fe1:Fe O_vac:O'), got {raw!r}",
                hint=_SPECIES_HINT,
            )
        mapping: dict[str, str] = {}
        for i in range(0, len(tokens), 2):
            mapping[tokens[i]] = tokens[i + 1]
        return mapping
    raise _error(
        _UNRESOLVED_SPECIES_LABEL,
        "species_map needs a 'species' parameter (a label→symbol map or 'Fe1:Fe O_vac:O')",
        hint=_SPECIES_HINT,
    )


def _recover_reference_symbols(parameters: dict[str, object]) -> list[str]:
    """The per-atom symbols for the ``upload_reference`` choice, drawn from a matching
    reference structure (Part 4 §3.3): the CLI injects a parsed ``reference``
    CanonicalObject (``cli._inject_references``); its frame-0 per-atom symbols are
    returned in order, indexed by atom, and applied directly (never collapsed into a
    label→symbol map). A reference whose atom count does not match this input is refused
    in ``_parse_core``, never silently trimmed."""
    ref = parameters.get("reference")
    if ref is None:
        raise _error(
            _UNRESOLVED_SPECIES_LABEL,
            "upload_reference needs a 'reference' parameter (the parsed reference structure); "
            "pass --recover missing_species=upload_reference,file=PATH",
            hint=_SPECIES_HINT,
        )
    reference = cast(CanonicalObject, ref)
    return [str(s) for s in reference.frames[0].atoms.symbols]


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


def _system_number(system: dict[str, _NamelistEntry], key: str) -> float | None:
    """A numeric &system fact, or ``None`` when absent; a non-numeric value is malformed."""
    value = system.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _error(
            _MALFORMED_NAMELIST,
            f"&system {key} must be numeric, found {value!r}",
            location="&system",
        )
    return float(value)


def _system_celldm(system: dict[str, _NamelistEntry]) -> dict[int, float] | None:
    """The ``celldm(1..6)`` values as ``{index: value}``, or ``None`` when absent. A scalar
    ``celldm`` (no indices) or a non-numeric element is malformed."""
    entry = system.get("celldm")
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise _error(
            _MALFORMED_NAMELIST,
            "&system celldm must be an indexed array (celldm(1), celldm(2), …)",
            location="&system",
        )
    out: dict[int, float] = {}
    for index, value in entry.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise _error(
                _MALFORMED_NAMELIST,
                f"&system celldm({index}) must be numeric, found {value!r}",
                location="&system",
            )
        out[int(index)] = float(value)
    return out


def _system_abc(
    system: dict[str, _NamelistEntry],
) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
    """The ``A, B, C, cosAB, cosAC, cosBC`` crystallographic spelling as a 6-tuple of
    floats (``None`` when a value is not declared)."""
    return (
        _system_number(system, "a"),
        _system_number(system, "b"),
        _system_number(system, "c"),
        _system_number(system, "cosab"),
        _system_number(system, "cosac"),
        _system_number(system, "cosbc"),
    )


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
        #
        # M52-S1 (D195): a **pw.x output** also carries ATOMIC_POSITIONS cards (and is the
        # only file that carries the `Program PWSCF` banner), so once qe_pw_out registers,
        # the bare ATOMIC_POSITIONS signal is no longer input-unique. The banner is the
        # discriminator — a pw.x *input* never contains it — and an output is the output
        # parser's, so the input parser defers to it (never a 1.0-vs-1.0 ambiguity on every
        # pw.out).
        text = head.decode("utf-8", errors="replace")
        if "Program PWSCF" in text:
            return 0.0
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
        """Whole-file read: ``ATOMIC_SPECIES`` labels resolve through QE's documented
        label rule (M50-S3), masses promote to ``atoms.masses``, recognized simulation
        context routes to ``simulation.extra``, and everything else is carried verbatim
        under the Part 2 §6.1 routing rule with the ``QEIN_UNMAPPED_ENTRY_CARRIED``
        warning (kept + reported, never refused)."""
        canonical, issues = self._parse_core(stream, filename=filename)
        return ParseResult(canonical=canonical, issues=issues)

    def _parse_core(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        label_map: Mapping[str, str] | None = None,
        per_atom_symbols: list[str] | None = None,
    ) -> tuple[CanonicalObject, list[ParseIssue]]:
        """The one read path, shared by ``parse`` and ``parse_recover`` (D191).

        ``label_map`` (the ``missing_species=species_map`` preset: label → element) and
        ``per_atom_symbols`` (the ``upload_reference`` preset: the reference's per-atom
        symbols) are the parse-time recovery inputs; the defaults honour the file's own
        declarations and refuse honestly when an ``ATOMIC_SPECIES`` label resolves to no
        element (P4 — never guessed, and the existing ``missing_species`` scenario is
        reused, never a QE-specific recovery).
        """
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
        else:
            # S1's reading (unchanged in S2): an absent ibrav is treated as the explicit-
            # cell path. QE marks ibrav REQUIRED; the refusal-of-missing-ibrav decision
            # is noted in D190 for a later milestone to pick up.
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
            location = f"line {i + 1}"  # the card header line; block-relative blanks
            # (skipped by _read_card_block) make an i-minus-len(block) count wrong.
            block, i = _read_card_block(lines, i + 1)
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
                # M50-S3 (D191): the schema has no canonical k-point model — stated, not
                # modeled; the card rides verbatim as structured custom data.
                lead = _unmapped_card_lead(keyword)
                if keyword == "K_POINTS":
                    unmapped_notes.append(
                        f"{lead} in user_metadata.custom_global[{_UNMAPPED_CARDS_KEY!r}]."
                    )
                else:
                    unmapped_notes.append(
                        f"{lead} in user_metadata.custom_global[{_UNMAPPED_CARDS_KEY!r}] "
                        "(M50-S3 routes it under the Part 2 §6.1 carry-through rule)."
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
        # --- species labels -> elements (M50-S3, D191) --------------------------------
        # QE's documented label rule lives in the shared _qe core (species_symbol): the
        # element is the leading 1–2 characters that form an element symbol, tried 2 then
        # 1 (Fe1 → Fe, O_vac → O). Each resolution is recorded; a label whose leading
        # characters form no element refuses QEIN_UNRESOLVED_SPECIES_LABEL with the
        # shared supply_species hint (the existing missing_species scenario, Part 4 §3.3)
        # unless parse_recover supplied a label_map (species_map) or per-atom symbols
        # (upload_reference) — never guessed, never a QE-specific recovery invented (D191).
        species_labels = {label for label, _, _ in species_rows}
        label_symbols: dict[str, str] = {}
        species_notes: list[str] = []
        for label, mass, pseudo in species_rows:
            symbol, _ = species_symbol(label)
            source = "QE's documented label rule"
            if symbol is None and label_map is not None:
                mapped = label_map.get(label)
                if mapped is not None:
                    symbol = normalize_symbol(mapped)
                    source = "the supplied species_map"
            if symbol is not None:
                label_symbols[label] = symbol
                species_notes.append(
                    f"ATOMIC_SPECIES label {label!r} resolves to element {symbol} "
                    f"({source}); its declared mass {mass} u and pseudopotential "
                    f"{pseudo!r} are carried verbatim."
                )
            elif per_atom_symbols is None:
                raise _error(
                    _UNRESOLVED_SPECIES_LABEL,
                    f"ATOMIC_SPECIES label {label!r} resolves to no element (QE's label "
                    "rule: the leading 1–2 characters that form an element symbol); supply "
                    "a label→element species_map or upload_reference through the existing "
                    "missing_species recovery to complete the read",
                    location="ATOMIC_SPECIES",
                    hint=_SPECIES_HINT,
                )
            else:
                # upload_reference is active: per-atom symbols supersede label resolution;
                # the declared table still rides verbatim with its mass and pseudopotential.
                species_notes.append(
                    f"ATOMIC_SPECIES label {label!r} resolves to no element under QE's "
                    "label rule; element symbols come from the uploaded reference per atom "
                    "(the declared table rides verbatim)."
                )

        for label, *_ in position_rows:
            if label not in species_labels:
                raise _error(
                    _MALFORMED_CARD,
                    f"ATOMIC_POSITIONS labels an atom {label!r} that ATOMIC_SPECIES does not "
                    f"declare (species: {', '.join(sorted(species_labels))})",
                    location="ATOMIC_POSITIONS",
                )
        if per_atom_symbols is not None:
            if len(per_atom_symbols) != nat:
                raise _error(
                    _UNRESOLVED_SPECIES_LABEL,
                    f"upload_reference supplies {len(per_atom_symbols)} element symbols for "
                    f"nat = {nat} atoms; the reference must match the input's atom count — "
                    "refusing rather than silently trimming",
                    location="ATOMIC_POSITIONS",
                    hint=_SPECIES_HINT,
                )
            symbols = list(per_atom_symbols)
        else:
            symbols = [label_symbols[label] for label, *_ in position_rows]

        # --- the two lattice-parameter spellings (celldm(1..6) / A,B,C,cosAB,cosAC,cosBC)
        # QE's documented contract is "specify either, NOT both" (INPUT_PW &system ibrav);
        # D190 corrects S1's note (which claimed "A wins"): both-present is refused, never
        # silently resolved (P4).
        celldm_map = _system_celldm(system)
        abc_values = _system_abc(system)
        # ``_system_abc`` always returns the 6-tuple (possibly all ``None``); the core
        # wants ``None`` for the absent spelling.
        abc_declared = any(value is not None for value in abc_values)
        abc_spelling = abc_values if abc_declared else None
        celldm1 = celldm_map.get(1) if celldm_map else None
        a_value = abc_values[0]
        if celldm1 is not None and a_value is not None:
            raise _error(
                _MALFORMED_NAMELIST,
                "&system declares both celldm(1) and A — QE's documented contract is "
                "'specify either, not both' (INPUT_PW &system ibrav); refusing rather than "
                "silently preferring one (D190)",
                location="&system",
            )
        alat: float | None
        alat_note: str | None
        alat, alat_note = alat_angstrom(celldm1=celldm1, a=a_value)

        # --- the lattice: explicit cell (ibrav = 0) or the ibrav expansion (S2) --------
        lattice: np.ndarray
        cell_note: str
        lattice_source: str
        if ibrav == 0:
            if cell_rows is None:
                raise _error(
                    _MALFORMED_CARD,
                    "missing required card CELL_PARAMETERS: ibrav = 0 declares an explicit cell, "
                    "and the lattice is never defaulted (P3)",
                    location="card section",
                )
            assert cell_unit is not None  # a CELL_PARAMETERS card always carries a unit
            try:
                lattice, cell_note = lattice_from_cell_parameters(
                    np.asarray(cell_rows, dtype=float), cell_unit, alat=alat
                )
            except ValueError as exc:
                raise _error(_MALFORMED_CARD, str(exc), location="card section") from exc
            lattice_source = cell_unit
        else:
            if cell_rows is not None:
                raise _error(
                    _MALFORMED_CARD,
                    f"CELL_PARAMETERS contradicts ibrav = {ibrav}: a pw.x input declares the "
                    "cell either explicitly (ibrav = 0) or through the Bravais lattice "
                    "(ibrav ≠ 0), never both — refusing the contradiction rather than "
                    "silently preferring one (D190)",
                    location="CELL_PARAMETERS",
                )
            if alat is None:
                raise _error(
                    _MALFORMED_NAMELIST,
                    f"ibrav = {ibrav} requires the lattice scale: &system must declare "
                    "celldm(1) (bohr) or A (angstrom) — the expansion is never run without "
                    "a scale (P3)",
                    location="&system",
                )
            try:
                lattice, cell_note = lattice_from_ibrav(
                    ibrav, celldm=celldm_map, abc=abc_spelling, alat=alat
                )
            except UnsupportedIbravError as exc:
                raise _error(_UNSUPPORTED_IBRAV, str(exc), location="&system") from exc
            except ValueError as exc:
                raise _error(_MALFORMED_NAMELIST, str(exc), location="&system") from exc
            lattice_source = f"ibrav={ibrav}"

        # --- positions (the deterministic boundary, recorded) ---------------------------
        if positions_unit == "alat" and alat is None:
            raise _error(
                _MALFORMED_CARD,
                "an alat-relative card is declared but &system carries neither celldm(1) "
                "nor A to resolve alat; refusing rather than assuming QE's 1-bohr default "
                "(P3)",
                location="&system",
            )
        try:
            raw_xyz = np.asarray([[x, y, z] for _, x, y, z in position_rows], dtype=float)
            cartesian, pos_note = positions_cartesian(
                raw_xyz, positions_unit, lattice=lattice, alat=alat
            )
        except ValueError as exc:
            raise _error(_MALFORMED_CARD, str(exc), location="card section") from exc

        # --- masses + pseudopotentials (present-with-value, P3; never dropped, P1) -----
        # QE requires a numeric mass per ATOMIC_SPECIES line (enforced in
        # ``_parse_atomic_species``), so atoms.masses is always the declared values —
        # never a fabricated default, and absence stays None (P3).
        mass_by_label = {label: mass for label, mass, _ in species_rows}
        masses = np.asarray([mass_by_label[label] for label, *_ in position_rows], dtype=float)
        pseudopotentials = {label: pseudo for label, _, pseudo in species_rows}

        # --- simulation metadata (recognized context -> simulation.extra, §6.1) --------
        sim_extra: dict[str, str] = {}
        for name, keys in _SIMULATION_EXTRA_KEYS.items():
            entries_for_name = namelists.get(name)
            if entries_for_name is None:
                continue
            for key in keys:
                if key in entries_for_name:
                    sim_extra[key] = str(entries_for_name[key])

        # --- provenance (the conversions are never silent) ----------------------------
        parse_notes: list[str] = []
        parse_notes.extend(default_unit_notes)
        if alat_note is not None:
            parse_notes.append(alat_note)
        parse_notes.append(cell_note)
        parse_notes.append(pos_note)
        parse_notes.append(pbc_note())
        parse_notes.extend(species_notes)
        parse_notes.append(
            "Declared ATOMIC_SPECIES masses promote to atoms.masses (present-with-value, "
            "P3); pseudopotential filenames ride "
            f"user_metadata.custom_global[{_PSEUDOPOTENTIALS_KEY!r}] (label → filename)."
        )
        if sim_extra:
            parse_notes.append(
                "Recognized simulation context routes to simulation.extra under the Part 2 "
                f"§6.1 carry-through routing rule: {', '.join(sorted(sim_extra))}."
            )
        parse_notes.extend(unmapped_notes)

        # --- carries (nothing is dropped, P1) -----------------------------------------
        custom_global: dict[str, JsonValue] = {
            _ATOMIC_SPECIES_KEY: {label: [mass, pseudo] for label, mass, pseudo in species_rows},
            _PSEUDOPOTENTIALS_KEY: dict(pseudopotentials),
        }
        issues: list[ParseIssue] = []
        carried_namelists: dict[str, dict[str, JsonValue]] = {}
        for name, entries in namelists.items():
            consumed = set(_CONSUMED_SYSTEM_KEYS) if name == "system" else set()
            consumed |= set(_SIMULATION_EXTRA_KEYS.get(name, frozenset()))
            remaining = {key: value for key, value in entries.items() if key not in consumed}
            if remaining:
                carried_namelists[name] = _jsonify_namelist(remaining)
                for key in remaining:
                    issues.append(
                        ParseIssue(
                            severity="warning",
                            code=_UNMAPPED_ENTRY_CARRIED,
                            message=(
                                f"&{name} entry {key!r} has no canonical schema field in this "
                                "milestone; carried verbatim in "
                                f"user_metadata.custom_global[{_NAMELISTS_KEY!r}] under the "
                                "Part 2 §6.1 carry-through routing — kept, never dropped (P1)."
                            ),
                            location=f"&{name}",
                        )
                    )
        if carried_namelists:
            # Recursive JsonValue aliases do not narrow on assignment; the nested dict is
            # structurally JsonValue (string keys, JSON scalars/values throughout).
            custom_global[_NAMELISTS_KEY] = cast(JsonValue, carried_namelists)
        for entry in unmapped_cards:
            keyword = str(entry["card"])
            wording = _unmapped_card_lead(keyword)
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=_UNMAPPED_ENTRY_CARRIED,
                    message=(
                        f"{wording} in user_metadata.custom_global[{_UNMAPPED_CARDS_KEY!r}] "
                        "under the Part 2 §6.1 carry-through routing — kept, never dropped (P1)."
                    ),
                    location=f"card {keyword}",
                )
            )
        if unmapped_cards:
            custom_global[_UNMAPPED_CARDS_KEY] = cast(JsonValue, unmapped_cards)

        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system=coordinate_system(positions_unit),
            source_units={"positions": positions_unit, "lattice_vectors": lattice_source},
            parse_notes=parse_notes,
        )
        canonical = CanonicalObject(
            frames=[
                Frame(
                    index=0,
                    atoms=AtomsBlock(symbols=symbols, positions=cartesian, masses=masses),
                    cell=Cell(lattice_vectors=lattice, pbc=(True, True, True)),
                )
            ],
            trajectory=None,  # a pw.x input is a single structure, no time axis (§3.2)
            # The input declares no program string (a pw.x input never does); recognized
            # simulation context routes to simulation.extra (M50-S3, D191).
            simulation=SimulationMetadata(extra=sim_extra) if sim_extra else None,
            provenance=provenance,
            user_metadata=UserMetadata(custom_global=custom_global),
        )
        return canonical, issues

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
        """Re-read under a parse-time recovery choice (Part 4 §3.3; D191).

        The only recoverable need is the shared ``supply_species`` hint (the existing
        ``missing_species`` scenario — the hazard is identical to the LAMMPS parsers', so
        one scenario is reused, never a QE-specific one invented): ``species_map`` applies
        the caller's label→element map, ``upload_reference`` applies the per-atom symbols
        of a matching reference structure. Either way the re-read goes through the *same*
        ``_parse_core`` path the ordinary parse uses, and the recovery is recorded with the
        ``QEIN_SPECIES_SUPPLIED`` warning (never silent, P1).``recovery_context`` is
        accepted and ignored: a QE input ever needs at most one parse-time recovery at a
        time (the M48 compound-recovery seam, additive with a default on the ABC).
        """
        if hint != _SPECIES_HINT:
            raise _error(
                _UNRESOLVED_SPECIES_LABEL,
                f"parse_recover does not handle hint {hint!r} (this parser's only "
                f"recoverable need is {_SPECIES_HINT!r}, the existing missing_species "
                "scenario)",
            )
        label_map: Mapping[str, str] | None = None
        per_atom_symbols: list[str] | None = None
        if choice == "species_map":
            label_map = _recover_label_map(parameters)
            wording = "a label→element species_map preset"
        elif choice == "upload_reference":
            per_atom_symbols = _recover_reference_symbols(parameters)
            wording = "the per-atom symbols of a matching reference structure"
        else:
            raise _error(
                _UNRESOLVED_SPECIES_LABEL,
                f"supply_species has no choice {choice!r} (offered: species_map, upload_reference)",
                hint=_SPECIES_HINT,
            )
        canonical, issues = self._parse_core(
            stream,
            filename=filename,
            label_map=label_map,
            per_atom_symbols=per_atom_symbols,
        )
        note = ParseIssue(
            severity="warning",
            code=_SPECIES_SUPPLIED,
            message=(
                "element symbols supplied via recovery choice "
                f"{choice!r} ({wording}); the ATOMIC_SPECIES labels that resolve to no "
                "element were completed from the supplied symbols"
            ),
        )
        return ParseResult(canonical=canonical, issues=[*issues, note])

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "ATOMIC_SPECIES labels resolve through QE's documented label rule "
                        "(decorated labels Fe1 → Fe, O_vac → O; each resolution recorded); "
                        "an unresolvable label refuses QEIN_UNRESOLVED_SPECIES_LABEL, "
                        "completable through the existing missing_species recovery."
                    ),
                ),
                "atoms.positions": full,
                "atoms.masses": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Declared ATOMIC_SPECIES masses promote to atoms.masses "
                        "(present-with-value, P3)."
                    ),
                ),
                "cell.lattice_vectors": full,
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Always (T,T,T) by format definition; a pw.x input carries no PBC.",
                ),
                "simulation.extra": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Recognized calculation/cutoff-convergence context (calculation, "
                        "ecutwfc, ecutrho, conv_thr, degauss, smearing, occupations) routes "
                        "here when declared (the §6.1 routing rule, M50-S3)."
                    ),
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "The ATOMIC_SPECIES table, pseudopotential filenames "
                        "(qe:pseudopotentials), unconsumed namelist entries, and "
                        "unrecognized cards carried verbatim (never dropped, P1); each "
                        "carried item emits the QEIN_UNMAPPED_ENTRY_CARRIED warning."
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
