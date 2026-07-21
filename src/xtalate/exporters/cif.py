"""CIF exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v0.4 M19).

Writes a single-block CIF: cell **parameters** derived from the canonical lattice vectors,
atom sites in **fractional** coordinates, and the block-level tags the parser carried through.

**Always the identity operation, always the full atom list (DECISIONS.md D68).** The Canonical
Object holds the expanded cell — M18 applies whatever operations a source CIF declared — so the
only symmetry true of the coordinates being written is the identity, and the file says so with a
one-entry ``_space_group_symop_operation_xyz`` loop and no space-group symbol at all. A
``cell.space_group`` the source carried is declared ``NONE`` here and lands in the pre-flight
``removed`` list with that reason, rather than being echoed above an atom list it no longer
describes. Re-deriving a setting *from* the coordinates is the project's Non-Goal, so the compact
asymmetric-unit form is not on offer at all; what is written is a complete, correct, verbose file.

**Two conversions at the boundary**, both the exact inverses of what the parser does on the way
in: Cartesian Å → fractional against the lattice, and lattice vectors → ``_cell_length_*`` /
``_cell_angle_*``. Neither is an interpretation — a cell has the same lengths and angles however
it is spelled — but both are floating-point, so they are noted rather than assumed lossless.
"""

from __future__ import annotations

import math
from typing import Any, BinaryIO

import numpy as np

from xtalate.schema import CanonicalObject
from xtalate.schema.paths import OCCUPANCY_CUSTOM_KEY
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
)

FORMAT_ID = "cif"

#: The data block heading, round-tripped from the name the parser recorded.
_BLOCK_NAME_KEY = "cif:data_block_name"
_DEFAULT_BLOCK_NAME = "xtalate"

#: The per-atom keys this exporter writes back, each to the ``_atom_site`` column it came from.
#: Naming them in ``writable_custom_keys`` is what tells the pre-flight diff that CIF genuinely
#: *represents* occupancy — the P6 hook M19 slice 2 built — rather than merely carrying the
#: numbers as an unlabelled column, which is what every other Phase 1 target does.
_LABEL_KEY = "cif:atom_site_label"
_TYPE_SYMBOL_KEY = "cif:type_symbol"
_WRITABLE_PER_ATOM = [_LABEL_KEY, _TYPE_SYMBOL_KEY, OCCUPANCY_CUSTOM_KEY]

#: ``simulation.extra`` keys that must **not** be written back as CIF tags, though every other
#: ``cif:``-prefixed key is. ``cif:symmetry_operations`` is the source's declared operation list,
#: which is exactly what D68 refuses to put above a full atom list — re-emitting it would make the
#: next reader expand an already-expanded structure. ``cif:charge_scheme`` is Xtalate's own label
#: for what ``electronic.charges`` holds, not a tag any CIF dictionary defines.
_UNWRITABLE_EXTRA_KEYS = frozenset({"cif:symmetry_operations", "cif:charge_scheme"})

#: Tags that **identify a space group**, and therefore must not be written above the expanded
#: full-cell atom list, for exactly the reason D68 withholds the Hermann-Mauguin symbol (D72).
#:
#: The parser already keeps the four *name* spellings out of ``simulation.extra``
#: (``_validate.SPACE_GROUP_NAME_TAGS``), but a space group is equally identified by its
#: International Tables *number* — ``_space_group_IT_number 225`` is ``Fm-3m`` as surely as the
#: symbol is — and databases mint their own symbol spellings (COD writes
#: ``_cod_original_sg_symbol_H-M``). Those reached ``simulation.extra`` and were written back, so
#: the output asserted a 192-operation group above an already-expanded cell carrying only the
#: identity: the silent re-expansion D66/D67/D68 exist to prevent, emitted by our own writer, while
#: the report claimed ``cell.space_group`` had been removed.
#:
#: The criterion is *identification*, not mention: a tag from which a reader can recover the
#: operation set is held back. A tag naming only the **crystal system** or **cell setting**
#: (``_space_group_crystal_system``, ``_symmetry_cell_setting``) is not — it says the cell is
#: cubic, which stays true of the written cell, and no operations follow from it.
#:
#: Both an exact set and a marker scan, because neither alone is right: the set is the predictable,
#: inspectable statement of what we hold back, and the markers catch the vendor-prefixed variants
#: that a fixed list silently misses — which is the bug being fixed here.
_SPACE_GROUP_ID_TAGS = frozenset(
    {
        "space_group_it_number",
        "symmetry_int_tables_number",
        "space_group_name_h-m_alt",
        "symmetry_space_group_name_h-m",
        "space_group_name_hall",
        "symmetry_space_group_name_hall",
    }
)
_SPACE_GROUP_ID_MARKERS = ("sg_symbol", "space_group_name", "int_tables_number", "it_number")


def _identifies_space_group(tag: str) -> bool:
    """Whether a bare CIF tag name (no leading underscore, lowercased) pins a space group."""
    return tag in _SPACE_GROUP_ID_TAGS or any(m in tag for m in _SPACE_GROUP_ID_MARKERS)


_EXTRA_PREFIX = "cif:"

# Characters that force a CIF value to be quoted rather than written bare.
_UNQUOTED_LEADERS = ("_", "#", "$", "[", "]", "'", '"', ";")
_RESERVED_WORDS = ("data_", "loop_", "global_", "save_", "stop_")
#: Values that ARE the unknown/inapplicable markers, and so must always be quoted to be written
#: as data. A bare ``?`` means "unknown" and a bare ``.`` means "inapplicable"; a source that
#: wrote ``'?'`` in quotes stated the one-character string. ``Token.quoted`` exists precisely to
#: keep those apart on the way in, and writing the literal bare threw that distinction away —
#: turning a value the source stated into an absence, indistinguishable from the ``?`` this
#: exporter writes for a genuinely missing site value.
_MARKER_VALUES = ("?", ".")


def _fmt(x: float) -> str:
    return repr(float(x))


def _quote(value: str) -> str:
    """One CIF data value, quoted only as much as the grammar requires.

    Values arrive here verbatim from the source file, so the job is to spell them so a reader
    recovers the identical string — never to normalise them. A value containing a newline can only
    be written as a semicolon-delimited text field, which is the one form with no escape sequence
    at all, so it is also the fallback for a value that contains both quote characters.
    """
    if value == "":
        return "''"
    if "\n" in value:
        return f"\n;{value}\n;"
    lowered = value.lower()
    needs_quote = (
        any(c.isspace() for c in value)
        or value.startswith(_UNQUOTED_LEADERS)
        or value in _MARKER_VALUES
        or any(lowered.startswith(word) for word in _RESERVED_WORDS)
    )
    if not needs_quote:
        return value
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return f"\n;{value}\n;"


#: The exact cell angles, and the tolerance within which a computed angle is recognised as one.
#:
#: This is the inverse of the parser's ``_EXACT_COS_SIN_DEG`` table, and it has to exist for that
#: table to be worth anything (D73). The parser builds a 120° cell from cos = −0.5 exactly, but the
#: return trip goes through ``acos`` of a dot product over vector norms, and ``sqrt(3)/2`` squared
#: is not ``0.75`` — so the angle comes back 120.000000000000014, misses the parser's table on the
#: next read, and hop 2 gets a lattice with a spurious tilt. CIF→CIF was therefore not idempotent
#: for any hexagonal, trigonal or rhombohedral cell: exactly the angles the parser's table was
#: written to protect.
#:
#: 1e-9° is roughly five orders of magnitude below the precision CIF states angles to (1e-4°) and
#: five above the ~1e-14° error being absorbed, so it cannot reach a value a source really meant.
_EXACT_ANGLES_DEG = (30.0, 60.0, 90.0, 120.0, 150.0)
_ANGLE_SNAP_TOLERANCE_DEG = 1e-9


def _snap_exact_angle(degrees: float) -> float:
    """A computed cell angle, snapped to the exact crystallographic value it is reproducing."""
    for exact in _EXACT_ANGLES_DEG:
        if abs(degrees - exact) <= _ANGLE_SNAP_TOLERANCE_DEG:
            return exact
    return degrees


def cell_parameters(lattice: np.ndarray) -> tuple[tuple[float, float, float], tuple[float, ...]]:
    """Lattice vectors (rows a, b, c, Å) → ``((a, b, c), (alpha, beta, gamma))`` in Å and degrees.

    The inverse of the parser's ``lattice_from_parameters``, including its exact-angle table (see
    ``_EXACT_ANGLES_DEG``), and the reason the round-trip holds regardless of orientation: lengths
    and angles are rotation-invariant, so a cell that was re-oriented on the way in (or arrived
    from a format that states vectors directly) comes back out with the parameters it always had.
    ``alpha`` is the angle between **b** and **c**, per the crystallographic convention that each
    angle is opposite its like-named axis.

    The two halves live in different layers (``parsers.cif._build`` and here) and so cannot share
    the table today; ``tests/exporters/test_cif.py`` pins them as mutual inverses meanwhile.
    """
    a, b, c = (np.asarray(row, dtype=float) for row in lattice)
    lengths = tuple(float(np.linalg.norm(v)) for v in (a, b, c))

    def angle(u: np.ndarray, v: np.ndarray, lu: float, lv: float) -> float:
        # Clamped because a floating-point dot product of near-parallel vectors can leave the
        # cosine a few ulp outside [-1, 1], where acos is a domain error rather than 0° or 180°.
        cosine = float(np.dot(u, v)) / (lu * lv)
        return _snap_exact_angle(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))

    angles = (
        angle(b, c, lengths[1], lengths[2]),
        angle(a, c, lengths[0], lengths[2]),
        angle(a, b, lengths[0], lengths[1]),
    )
    return lengths, angles  # type: ignore[return-value]


def _to_fractional(positions: np.ndarray, lattice: np.ndarray) -> np.ndarray:
    """Cartesian Å → fractional against ``lattice`` (rows a, b, c).

    ``cart = frac @ lattice``, so ``frac`` solves ``lattice.T @ frac.T = cart.T``. Solved rather
    than multiplied by an explicit inverse, for the same conditioning reason XDATCAR gives: on the
    skewed cells low-symmetry crystals routinely have, the solve keeps the inversion error at the
    ulp level the declared representational bound assumes.
    """
    return np.asarray(np.linalg.solve(lattice.T, positions.T).T)


def _column(custom_per_atom: dict[str, Any], key: str, n_atoms: int) -> list[Any] | None:
    """One ``custom_per_atom`` column as a plain list, or ``None`` if it is absent or the wrong
    length. A mismatched length is treated as absent rather than raising: it means the column
    belongs to some other structure, and writing part of it against these atoms would attach one
    structure's site facts to another's (**P1**)."""
    values = custom_per_atom.get(key)
    if values is None:
        return None
    column = list(values)
    return column if len(column) == n_atoms else None


def _or_else(column: list[Any] | None, index: int, fallback: Any) -> Any:
    """``column[index]`` when the source stated it there, else ``fallback``.

    Per-atom rather than per-column, because the column-level ``or`` this replaced tested
    truthiness: an all-``None`` column is a non-empty list, so it won the ``or`` and suppressed
    the fallback for every atom.
    """
    if column is None or column[index] is None:
        return fallback
    return column[index]


def _generated_labels(symbols: list[str]) -> list[str]:
    """``_atom_site_label`` values for a structure that carries none — ``Na1``, ``Na2``, ``Cl1``.

    A label is CIF's key for the site row, so a file cannot omit it; but it is an *identifier*,
    not a measurement, and inventing one asserts nothing about the structure. That is the whole of
    why this is not a **P4** violation, and why the parser's own labels are preferred when present:
    a source that named its sites gets its names back.
    """
    seen: dict[str, int] = {}
    labels = []
    for symbol in symbols:
        seen[symbol] = seen.get(symbol, 0) + 1
        labels.append(f"{symbol}{seen[symbol]}")
    return labels


def _site_value(value: Any) -> str:
    """One ``_atom_site`` cell, written as the source spelled it.

    ``None`` is the absence convention's ``?`` coming back out (**P3**): the source said the value
    was unknown, and a CIF says that with ``?``, so the statement survives the round-trip as a
    statement of unknownness rather than becoming a number.
    """
    if value is None:
        return "?"
    if isinstance(value, (int, float, np.floating, np.integer)):
        return _fmt(float(value))
    return _quote(str(value))


class CifExporter(ExporterPlugin):
    """Crystallographic Information File writer (Part 3 §3).

    Single-structure by declaration (``max_frames = 1``), so a trajectory reaches this exporter
    only after the Conversion Engine's ``frame_selection`` recovery has recorded the reduction as
    an Assumption (Part 4 §3) — the same contract POSCAR has.
    """

    format_id = FORMAT_ID
    format_name = "Crystallographic Information File"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        if len(canonical.frames) != 1:
            raise ValueError(
                "a CIF data block holds a single structure; reduce the trajectory to one frame "
                "via the Conversion Engine's frame_selection recovery before export (Part 4 §3)"
            )
        frame = canonical.frames[0]
        atoms = frame.atoms
        cell = frame.cell
        if cell is None or cell.lattice_vectors is None:
            raise ValueError(
                "CIF states a cell for every structure and has no way to describe an unbounded "
                "one; supply cell.lattice_vectors via the missing_lattice recovery before export "
                "(Part 4 §3)"
            )

        lattice = np.asarray(cell.lattice_vectors, dtype=float)
        lengths, angles = cell_parameters(lattice)
        fractional = _to_fractional(np.asarray(atoms.positions, dtype=float), lattice)

        block_name = canonical.user_metadata.custom_global.get(_BLOCK_NAME_KEY)
        name = str(block_name) if block_name else _DEFAULT_BLOCK_NAME
        out: list[str] = [f"data_{name.split()[0] if name.split() else _DEFAULT_BLOCK_NAME}", ""]

        for tag, value in zip(("a", "b", "c"), lengths, strict=True):
            out.append(f"_cell_length_{tag}     {_fmt(value)}")
        for tag, value in zip(("alpha", "beta", "gamma"), angles, strict=True):
            out.append(f"_cell_angle_{tag}  {_fmt(value)}")
        out.append("")

        # D68: the identity operation, and *only* the identity operation, above the complete atom
        # list that follows. No `_space_group_name_H-M_alt` accompanies it. The loop is the
        # machine-actionable statement — it says "apply nothing, these atoms are all of them" — and
        # a 'P 1' symbol beside it would say the same thing a second time in a canonical field the
        # source did not populate, which is why the symbol is omitted rather than written.
        out.append("loop_")
        out.append("_space_group_symop_operation_xyz")
        out.append("'x, y, z'")
        out.append("")

        out.extend(self._carried_tags(canonical))
        out.extend(self._atom_site_loop(canonical, atoms.symbols, fractional))
        stream.write(("\n".join(out) + "\n").encode("utf-8"))

    def _carried_tags(self, canonical: CanonicalObject) -> list[str]:
        """The block-level tags the parser carried into ``simulation.extra``, written back.

        Source order, not sorted: these came out of a file in the order that file stated them, and
        a conversion has no reason to rearrange the source's own bibliography.
        """
        if canonical.simulation is None:
            return []
        lines = []
        for key, value in canonical.simulation.extra.items():
            if not key.startswith(_EXTRA_PREFIX) or key in _UNWRITABLE_EXTRA_KEYS:
                continue
            tag = key[len(_EXTRA_PREFIX) :]
            if _identifies_space_group(tag):
                continue
            lines.append(f"_{tag}  {_quote(str(value))}")
        return [*lines, ""] if lines else []

    def _atom_site_loop(
        self, canonical: CanonicalObject, symbols: list[str], fractional: np.ndarray
    ) -> list[str]:
        per_atom = canonical.user_metadata.custom_per_atom
        n = len(symbols)
        # Fallbacks are applied **per atom**, not per column. `or` tests truthiness, and a column
        # of all-`None` — a source whose _atom_site_type_symbol was `?` on every row — is a
        # non-empty list and therefore truthy, so the column-level fallback never fired and every
        # atom was written `?` while atoms.symbols held perfectly good elements. Each site falls
        # back on its own, so a column that is unknown for some rows and stated for others gets
        # the source's value where there is one and the derived value where there is not.
        source_labels = _column(per_atom, _LABEL_KEY, n)
        generated = _generated_labels(symbols)
        labels = [_or_else(source_labels, i, generated[i]) for i in range(n)]
        # The raw type symbol carries the oxidation-state suffix ('Fe3+') the element alone drops,
        # so a source that spelled one gets it back; otherwise the element symbol is the type.
        source_types = _column(per_atom, _TYPE_SYMBOL_KEY, n)
        types = [_or_else(source_types, i, symbols[i]) for i in range(n)]
        occupancies = _column(per_atom, OCCUPANCY_CUSTOM_KEY, n)

        tags = [
            "_atom_site_label",
            "_atom_site_type_symbol",
            "_atom_site_fract_x",
            "_atom_site_fract_y",
            "_atom_site_fract_z",
        ]
        if occupancies is not None:
            tags.append("_atom_site_occupancy")

        lines = ["loop_", *tags]
        for i in range(n):
            row = [
                _site_value(labels[i]),
                _site_value(types[i]),
                *(_fmt(v) for v in fractional[i]),
            ]
            if occupancies is not None:
                row.append(_site_value(occupancies[i]))
            lines.append("  " + "  ".join(row))
        return lines

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        none = FieldCapability(level=CapabilityLevel.NONE)
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": full,
                "atoms.positions": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Written as fractional _atom_site_fract_* against the cell.",
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Written as _cell_length_* / _cell_angle_* parameters; lengths and "
                    "angles are orientation-independent, so the cell is preserved exactly even "
                    "though its absolute orientation in the lab frame is not a CIF concept.",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="CIF describes a crystal, so periodicity is implied and never written; "
                    "only fully periodic (T,T,T) is representable.",
                ),
                # D68. The reason travels with the capability so it reaches the report unedited.
                "cell.space_group": FieldCapability(
                    level=CapabilityLevel.NONE,
                    notes="Xtalate writes the identity operation and the full explicit atom list, "
                    "with no space-group symbol, because the Canonical Object holds the expanded "
                    "cell; a source symbol would assert a setting the written coordinates no "
                    "longer encode, and re-deriving one from coordinates is a Non-Goal "
                    "(DECISIONS.md D68).",
                ),
                "dynamics.velocities": none,
                "dynamics.forces": none,
                "dynamics.constraints": none,
                "electronic.total_energy": none,
                "electronic.stress": none,
                "electronic.charges": FieldCapability(
                    level=CapabilityLevel.NONE,
                    notes="CIF states charges per atom *type* (_atom_type_oxidation_number), not "
                    "per atom; writing the canonical per-atom array back is a v0.4 cut-line item.",
                ),
                "electronic.magnetic_moments": none,
                "simulation.extra": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Keys prefixed 'cif:' are written back as the block-level tags they came "
                    "from; other keys have no CIF tag spelling and are dropped. Two families are "
                    "held back deliberately: the declared symmetry operations, and any tag that "
                    "identifies a space group — its International Tables number or a database's "
                    "own symbol spelling — because the written atom list is the expanded full "
                    "cell and a reader honouring either would expand it a second time "
                    "(DECISIONS.md D68, D72). A tag naming only the crystal system is kept.",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only the data block name (cif:data_block_name).",
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Site label, raw type symbol and occupancy are written back to their "
                    "_atom_site columns; other per-atom columns (Wyckoff symbols, displacement "
                    "parameters) are not re-emitted in v0.4.",
                ),
                "user_metadata.custom_per_frame": none,
            },
            # Naming 'cif:occupancy' here is a positive claim that this format *represents* site
            # occupancy — the pre-flight diff reads exactly this to decide whether a partial
            # occupancy needs its warning (M19 slice 2), and CIF is the first target that earns
            # the suppression rather than merely carrying the numbers somewhere.
            writable_custom_keys={
                "user_metadata.custom_per_atom": _WRITABLE_PER_ATOM,
                "user_metadata.custom_global": [_BLOCK_NAME_KEY],
            },
            max_frames=1,
            required_fields=["atoms.symbols", "atoms.positions", "cell.lattice_vectors"],
            allows_open_boundaries=False,  # a CIF cell is a crystal lattice (Part 3 §4.2).
            representable_constraint_kinds=[],
            native_coordinate_system="fractional",
            lossy_notes=[
                "Written with the identity symmetry operation and every atom listed explicitly; "
                "no space-group symbol is emitted, and a source symbol is reported removed "
                "rather than echoed (DECISIONS.md D68).",
                "Cartesian positions are converted to fractional against the cell on write, so "
                "sub-ulp differences from the source Cartesian values are possible on round-trip.",
            ],
        )


def make_cif_exporter() -> CifExporter:
    return CifExporter()
