"""Stage 3 of the CIF reader: CIF-level invariants (DECISIONS.md D65).

The stage rule that keeps this module from collapsing into ``_build``: **this stage checks only
what is expressible without the Canonical Model, and imports nothing from ``xtalate.schema``.**
Required tags present, loop columns consistent, numerics parseable, symmetry expansion possible
— all statements about the CIF. Element-table validity, unit conventions and the absence
convention need schema knowledge and therefore belong to stage 4.

Symmetry is read here, not decided here: this stage parses the operations the file *declares*
into affine maps (``_symmetry``, M18) and hands them to stage 4, which applies them. What it
still refuses is the file that says expansion is required but does not say how —
``CIF_UNEXPANDABLE_SYMMETRY``, permanent parser behavior whose only resolution is an explicit
Recovery Workflow (D66). Such a file is never silently reduced to its asymmetric unit.
"""

from __future__ import annotations

import math
import re

from xtalate.parsers.cif._document import CifBlock, CifDocument, CifLoop
from xtalate.parsers.cif._symmetry import SymmetryOperation, parse_symops
from xtalate.sdk import ParseError, ParseIssue

# --- tag families -------------------------------------------------------------------------
# CIF renamed these between the legacy _symmetry_* set and the current _space_group_* set, and
# real files use both spellings — often within one file. Every lookup accepts all of them.

CELL_LENGTH_TAGS = ("_cell_length_a", "_cell_length_b", "_cell_length_c")
CELL_ANGLE_TAGS = ("_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma")
SPACE_GROUP_NAME_TAGS = (
    "_space_group_name_h-m_alt",
    "_symmetry_space_group_name_h-m",
    "_space_group_name_hall",
    "_symmetry_space_group_name_hall",
)
SYMOP_TAGS = ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz")
FRACT_TAGS = ("_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
CARTN_TAGS = ("_atom_site_cartn_x", "_atom_site_cartn_y", "_atom_site_cartn_z")
TYPE_SYMBOL_TAG = "_atom_site_type_symbol"
LABEL_TAG = "_atom_site_label"
#: The tags whose presence in a loop marks a block as *the structure block* (see ``select_block``).
#: Coordinates and identity, in both spellings — a block carrying any of these is describing atoms,
#: and a block carrying none of them is a header or a bibliography however many tags it has.
ATOM_SITE_TAGS = (*FRACT_TAGS, *CARTN_TAGS, TYPE_SYMBOL_TAG, LABEL_TAG)
OCCUPANCY_TAG = "_atom_site_occupancy"
ATOM_TYPE_SYMBOL_TAG = "_atom_type_symbol"
OXIDATION_NUMBER_TAG = "_atom_type_oxidation_number"

# A standard uncertainty in parentheses — "5.4310(2)" — is CIF's way of writing a value with its
# estimated error. The value is the number; the parenthesized digits are precision on the last
# figures. Stripping it is not laundering: the parenthesized part is *metadata about* the value,
# not a competing value, and dropping it silently would still be loss — so the builder records
# the raw spelling in provenance for any site that carried one.
_UNCERTAINTY = re.compile(r"^([+-]?[0-9.eE+-]+?)\(([0-9]+)\)$")


def _issue(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


def parse_number(raw: str, *, tag: str, line: int) -> float:
    """A CIF numeric value as a float, tolerating a standard uncertainty suffix.

    Non-finite values are rejected here rather than left to the Canonical Model. ``float()``
    accepts ``"nan"`` and ``"inf"``, and NaN then defeats every ordinary range guard downstream
    (``value <= 0.0`` is ``False`` for NaN), so the failure surfaced two stages later out of
    ``AtomsBlock`` construction as a raw ``pydantic.ValidationError`` — outside the ``ParseError``
    contract this parser owes its callers, and a stack trace rather than a structured error in the
    CLI. A CIF numeric field has no meaningful non-finite value, so this is a malformed number.
    """
    text = raw.strip()
    match = _UNCERTAINTY.match(text)
    if match:
        text = match.group(1)
    try:
        value = float(text)
    except ValueError as exc:
        raise _issue(
            "CIF_MALFORMED_NUMBER",
            f"{tag} is not a number: {raw!r}",
            location=f"line {line}",
        ) from exc
    if not math.isfinite(value):
        raise _issue(
            "CIF_MALFORMED_NUMBER",
            f"{tag} is not a finite number: {raw!r}",
            location=f"line {line}",
        )
    return value


def has_uncertainty(raw: str) -> bool:
    """Whether ``raw`` carried a parenthesized standard uncertainty."""
    return _UNCERTAINTY.match(raw.strip()) is not None


def select_block(document: CifDocument) -> tuple[CifBlock, list[ParseIssue]]:
    """The structure block, plus an issue naming any block this parser does not read.

    CIF blocks are **independent structures, not frames** — a two-block file is two crystals,
    not a two-frame trajectory — so they cannot be concatenated into one Canonical Object
    without inventing a time axis the file never declared. Reading one and naming the rest is
    therefore the honest reading (Part 3 §3 n.4). The rejected alternative, mapping blocks onto
    ``frames``, would present unrelated structures as a trajectory and make every downstream
    frame-selection operation meaningless.

    *Which* block is the structure block is a separate question from that principle, and taking
    ``blocks[0]`` answered it wrongly. A `data_global` header block carrying only bibliographic
    tags is standard in CCDC/CSD depositions, and a file opening with one was refused with
    `CIF_MISSING_CELL` — an error naming a cause that was not the problem, on a file that is
    complete and readable. The structure block is the first one carrying an ``_atom_site`` loop;
    a file with no such block anywhere falls back to the first, so the error it then raises is
    about the structure block's actual defect rather than about this choice.
    """
    if not document.blocks:
        raise _issue("CIF_NO_DATA_BLOCK", "file contains no 'data_' block")
    chosen = next(
        (b for b in document.blocks if any(b.find_loop(tag) is not None for tag in ATOM_SITE_TAGS)),
        document.blocks[0],
    )
    issues: list[ParseIssue] = []
    if len(document.blocks) > 1:
        skipped = [b.name for b in document.blocks if b is not chosen]
        issues.append(
            ParseIssue(
                severity="warning",
                code="CIF_ADDITIONAL_BLOCKS_NOT_READ",
                message=(
                    f"file contains {len(document.blocks)} data blocks; only {chosen.name!r} "
                    f"(the first carrying an _atom_site loop) was read. CIF blocks are "
                    f"independent structures, not frames, so the remaining blocks are not part "
                    f"of this structure and were not converted: {skipped}"
                ),
                location=f"line {chosen.line}",
            )
        )
    return chosen, issues


def validate_cell(
    block: CifBlock,
) -> tuple[tuple[float, float, float], tuple[float, float, float], set[str]]:
    """Cell lengths (Å) and angles (degrees), checked for physical sanity.

    The third element is the set of cell tags whose value carried a parenthesized standard
    uncertainty (``5.4310(2)``), which the builder folds into the same precision-loss note it
    already raises for coordinates. Reporting it here rather than only at the coordinates is not
    a refinement: real files put their uncertainties on the *lattice constants* far more often
    than on fractional coordinates, because coordinates at special positions are exact by
    symmetry (``0.``, ``0.5``) while a refined cell length essentially always has an esd. A note
    that covered only coordinates therefore covered the rare case and missed the usual one —
    silently, which is the part that made it a P5 defect rather than a cosmetic gap.
    """
    for tag in (*CELL_LENGTH_TAGS, *CELL_ANGLE_TAGS):
        if block.find_pair(tag) is None:
            raise _issue(
                "CIF_MISSING_CELL",
                f"required cell parameter {tag} is absent or unknown; a CIF structure "
                "cannot be placed without a complete cell",
                location=f"line {block.line}",
            )
    a, b, c = (
        parse_number(_require(block, tag), tag=tag, line=block.line_of(tag))
        for tag in CELL_LENGTH_TAGS
    )
    alpha, beta, gamma = (
        parse_number(_require(block, tag), tag=tag, line=block.line_of(tag))
        for tag in CELL_ANGLE_TAGS
    )
    lengths = (a, b, c)
    angles = (alpha, beta, gamma)
    for tag, value in zip(CELL_LENGTH_TAGS, lengths, strict=True):
        if value <= 0.0:
            raise _issue(
                "CIF_INVALID_CELL",
                f"{tag} must be positive, found {value}",
                location=f"line {block.line_of(tag)}",
            )
    for tag, value in zip(CELL_ANGLE_TAGS, angles, strict=True):
        if not 0.0 < value < 180.0:
            raise _issue(
                "CIF_INVALID_CELL",
                f"{tag} must lie strictly between 0 and 180 degrees, found {value}",
                location=f"line {block.line_of(tag)}",
            )
    uncertain = {
        tag
        for tag in (*CELL_LENGTH_TAGS, *CELL_ANGLE_TAGS)
        if has_uncertainty(_require(block, tag))
    }
    return lengths, angles, uncertain


def _rejoin_split_symops(values: list[str]) -> list[str]:
    """Repair a symop column the lexer split on the spaces inside unquoted operations.

    ``x, y, z`` written without quotes is three whitespace-separated tokens, so a single-column
    loop silently becomes three one-fragment rows — and the row-count check cannot catch it,
    because ``len(values) % 1`` is zero for any number of values. The failure surfaced two stages
    later as ``CIF_MALFORMED_SYMOP: 'x,' has 2 components``, naming a defect the file does not
    have. Strictly the file is malformed CIF 1.1; gemmi, ASE and PyCIFRW all read it, and D65's
    stage-1/2 seam exists so this reader can be swapped for gemmi, which argues for parity on
    files gemmi accepts.

    Repair only where it demonstrably works: fragments are joined until each accumulated string
    is a complete three-component triplet, and the result is returned **only** if every value
    became one. Otherwise the original list is handed back unchanged, so a genuinely malformed
    operation still raises its own error rather than being mangled into a neighbour. Nothing is
    warned about — no information is at risk here, and a warning firing on every unquoted file
    would be the noise D71 came to regret.
    """
    if all(v.count(",") == 2 for v in values):
        return values  # already whole; the overwhelmingly common quoted case
    rejoined: list[str] = []
    buffer = ""
    for value in values:
        buffer += value
        if buffer.count(",") == 2 and not buffer.endswith(","):
            rejoined.append(buffer)
            buffer = ""
    if buffer or not rejoined:
        return values  # a leftover fragment means this is not the defect being repaired
    return rejoined


def validate_symmetry(block: CifBlock) -> tuple[str | None, list[SymmetryOperation]]:
    """The declared space-group symbol and the declared symmetry operations, parsed.

    An empty operation list means the file needs no expansion — it declares no operations and
    either names no space group or names ``P 1``. Anything else is refused rather than read as
    a partial structure: a file whose atoms are an asymmetric unit must never be mistaken for a
    complete one, which is the failure where a conversion yields a fraction of the atoms, wrong
    stoichiometry, and a plausible-looking output file (D66).
    """
    symbol = block.find_pair(*SPACE_GROUP_NAME_TAGS)
    loop = None
    for tag in SYMOP_TAGS:
        loop = block.find_loop(tag)
        if loop is not None:
            ops = _rejoin_split_symops([op for op in (loop.column(tag) or []) if op is not None])
            break
    else:
        ops = []

    if loop is not None:
        return symbol, parse_symops(ops, line=loop.line)

    if symbol is not None and not _is_p1(symbol):
        raise _issue(
            "CIF_UNEXPANDABLE_SYMMETRY",
            f"file declares space group {symbol!r} but carries no symmetry-operation loop "
            f"({' or '.join(SYMOP_TAGS)}). Without the operations Xtalate cannot determine "
            "whether the listed sites are an asymmetric unit or the full cell, and supplying "
            "the operations from space-group tables would be data the file never declared "
            "(P4). The file is refused rather than read as a possibly-partial structure",
            location=f"line {block.line_of(*SPACE_GROUP_NAME_TAGS)}",
        )
    return symbol, []


def validate_atom_sites(block: CifBlock) -> tuple[CifLoop, tuple[str, str, str], bool]:
    """Locate the atom-site loop and its coordinate columns.

    Returns ``(loop, coordinate_tags, fractional)``. Fractional coordinates are preferred when
    both are present: they are CIF's native form (Part 3 §3), so reading them keeps the
    conversion one step shorter and records the honest ``original_coordinate_system``.
    """
    loop = block.find_loop(FRACT_TAGS[0]) or block.find_loop(CARTN_TAGS[0])
    if loop is None:
        raise _issue(
            "CIF_MISSING_ATOM_SITES",
            "file contains no _atom_site loop with fractional or Cartesian coordinates",
            location=f"line {block.line}",
        )
    fractional = all(loop.has(tag) for tag in FRACT_TAGS)
    if not fractional and not all(loop.has(tag) for tag in CARTN_TAGS):
        present = [t for t in (*FRACT_TAGS, *CARTN_TAGS) if loop.has(t)]
        raise _issue(
            "CIF_INCOMPLETE_COORDINATES",
            "the _atom_site loop needs all three coordinate columns (x, y and z); "
            f"found only {present}",
            location=f"line {loop.line}",
        )
    if not loop.has(TYPE_SYMBOL_TAG) and not loop.has(LABEL_TAG):
        raise _issue(
            "CIF_MISSING_SPECIES",
            f"the _atom_site loop carries neither {TYPE_SYMBOL_TAG} nor {LABEL_TAG}, so no "
            "element can be identified; symbols are required and are never invented "
            "(Part 2 §3.3)",
            location=f"line {loop.line}",
        )
    if not loop.rows:
        raise _issue(
            "CIF_EMPTY_ATOM_SITES",
            "the _atom_site loop declares columns but contains no rows",
            location=f"line {loop.line}",
        )
    return loop, (FRACT_TAGS if fractional else CARTN_TAGS), fractional


def validate_oxidation_numbers(block: CifBlock) -> dict[str, float]:
    """Declared formal oxidation states, keyed by the ``_atom_type_symbol`` they belong to.

    CIF states formal charge in a separate ``_atom_type`` loop rather than on the site, so the
    join key is the type symbol (``Fe3+``) the ``_atom_site`` rows also carry. An oxidation loop
    with no symbol column has nothing to join on and is refused rather than positionally guessed
    against the atom sites — the two loops are independent tables, and a file listing three atom
    types for a two-element structure would silently mis-assign every charge.

    Returns an empty mapping when the file declares no oxidation numbers, which is absence, not
    zero charge (**P3**): stage 4 leaves ``electronic.charges`` unset rather than filling it.
    """
    loop = block.find_loop(OXIDATION_NUMBER_TAG)
    if loop is None:
        return {}
    symbols = loop.column(ATOM_TYPE_SYMBOL_TAG)
    if symbols is None:
        raise _issue(
            "CIF_UNJOINABLE_OXIDATION_NUMBERS",
            f"the loop carrying {OXIDATION_NUMBER_TAG} has no {ATOM_TYPE_SYMBOL_TAG} column, so "
            "the declared charges cannot be attached to the atom sites they describe; matching "
            "them by row order would assign charges the file never paired",
            location=f"line {loop.line}",
        )
    numbers = loop.column(OXIDATION_NUMBER_TAG)
    assert numbers is not None  # the tag the loop was found by
    declared: dict[str, float] = {}
    for symbol, number in zip(symbols, numbers, strict=True):
        if symbol is None or number is None:
            continue  # '?' / '.' is absence on one row, not a defect in the loop (P3)
        key = symbol.strip()
        value = parse_number(number, tag=OXIDATION_NUMBER_TAG, line=loop.line)
        if key in declared and declared[key] != value:
            raise _issue(
                "CIF_CONFLICTING_OXIDATION_NUMBERS",
                f"atom type {key!r} is declared with two different oxidation numbers "
                f"({declared[key]} and {value}); the file states no way to choose between them",
                location=f"line {loop.line}",
            )
        declared[key] = value
    return declared


def _require(block: CifBlock, tag: str) -> str:
    value = block.find_pair(tag)
    assert value is not None  # guarded by the caller's presence loop
    return value


def _is_p1(symbol: str) -> bool:
    """Whether a space-group symbol denotes P 1 — the one group needing no expansion.

    P -1 is deliberately *not* P 1: it carries an inversion centre, so its sites are an
    asymmetric unit like any other non-trivial group.
    """
    return symbol.replace(" ", "").replace("_", "").lower() in {"p1", "p1(no.1)"}
