"""LAMMPS data (configuration / restart) parser (MASTER_SPEC Part 3 §3; v1.3 M48-S1).

The text ``data`` file a LAMMPS run reads with ``read_data`` and writes with ``write_data`` — a
single configuration (or a restart's text form), not a trajectory. Unlike the ``dump`` format
(M46), a data file is a **single frame**, so this parser is a plain whole-file ``parse`` (no
streaming): peak memory tracks the one configuration.

A data file is a title comment, a numeric *header* (counts, type counts, box), then named *body*
sections::

    <title comment>                       (line 0, free text — may be blank)

    <N> atoms                             header: counts + type counts + box, every line
    <K> atom types                        starting with a number; order is free
    <M> bonds                             (topology counts — no canonical home; carried)
    ...
    xlo xhi                               box edge params written *directly* (not the dump's
    ylo yhi                               axis-aligned bounding box) — box_from_edges, S1
    zlo zhi
    xy xz yz                              (optional tilt line)

    Masses                                body sections: a keyword line, a blank, then rows
                                          whose first token is an integer index
    1 12.011

    Atoms # full                          the atom style rides in the section comment
    1 1 1 -0.8 0.0 0.0 0.0

    Velocities
    1 0.0 0.0 0.0

    Bonds                                 (topology — carried verbatim; no canonical home)
    1 1 1 2

**The header/body boundary is the leading token.** Every header line begins with a number
(``300 atoms``, ``2 atom types``, ``0.0 10.0 xlo xhi``); every body *data* row begins with an
integer index (an atom id, a type id, a bond id); every body *section keyword* begins with a
letter (``Masses``, ``Atoms # full``, ``Pair Coeffs``). So the parser needs no exhaustive
section vocabulary: a line whose first token is not a number opens a section, and the header ends
at the first such line.

Honesty on every axis (Part 3 §3; the M48 plan):

* **Three facts a data file never states, resolved together, never guessed.** A data file
  declares no unit style, no element symbols (only numeric atom types), and — when the ``Atoms``
  section carries no ``# <style>`` comment — no atom style. All three are parse-time-blocking, so
  the initial parse refuses with a recoverable issue and the conversion is completed only once the
  caller names them (Part 4 §3.3, D174/D180): ``ambiguous_units`` (metal/real/si),
  ``missing_species`` (a type→symbol ``species_map`` or an ``upload_reference``), and
  ``ambiguous_atom_style`` (atomic/charge/full). They resolve in one compound recovery pass — the
  orchestrator threads every resolved choice back through ``parse_recover``'s ``recovery_context``
  (the M48 SDK seam) — and each becomes one recorded Assumption. A declared unit style outside the
  hand-verified table, or an ``Atoms # <style>`` naming a style this release does not support,
  is **not** an ambiguity to resolve — it refuses as unsupported, never guessed.
* **The three supported atom styles fix the column layout, nothing more.** ``atomic`` =
  ``id type x y z``; ``charge`` = ``id type q x y z``; ``full`` = ``id molecule-id type q x y z``.
  A complete trailing ``ix iy iz`` triple (image flags) is recognized on any style. The charge
  column feeds ``electronic.charges`` (charge/full only); the molecule-id feeds a carried per-atom
  array (full only) — neither is fabricated when the style does not carry it (P3).
* **Masses map to portable per-atom masses.** The ``Masses`` table (type → mass, in the style's
  mass unit) fills ``atoms.masses`` (amu) for every atom via its type — the cross-format-portable
  home and the section's sole canonical representation (a data→extXYZ conversion keeps masses; the
  data exporter regenerates the section from ``atoms.masses``, M48-S2). Absent ``Masses`` →
  ``atoms.masses`` stays ``None`` (P3). The raw section is carried in the topology payload *only*
  when it holds a mass ``atoms.masses`` cannot — a mass for a declared atom type that no atom uses
  — so a mass-only file reports no topology loss.
* **Topology is carried verbatim, never dropped, never interpreted.** Every body section that has
  no canonical home — ``Bonds``/``Angles``/``Dihedrals``/``Impropers``, every ``* Coeffs``
  block, and any section this release does not recognize — plus the header's topology count lines
  are carried under ``user_metadata.custom_global['lammps_data:topology']`` as verbatim rows with
  their section comments and file order. The warning ``LAMMPSDATA_TOPOLOGY_CARRIED`` states the
  carry; an *unrecognized* keyword additionally warns ``LAMMPSDATA_UNMAPPED_SECTION_CARRIED``. A
  data→extXYZ conversion drops this payload — the pre-flight predicts it and the Conversion Report
  records it (P1/P5).
* **Absent boundary is the one applied default, and it is announced.** A data file has a box but
  no boundary declaration (LAMMPS reads that from the input script's ``boundary`` command, not the
  file). A simulation box is periodic by the format's nature, so ``cell.pbc`` is set to
  ``(True, True, True)`` — LAMMPS's own ``p p p`` default — with a parse note stating it was
  *applied*, not read (distinct from POSCAR, where periodicity is format-defined). Nothing else
  is ever defaulted (P4).
* **Atoms are sorted by id.** LAMMPS does not guarantee ``Atoms`` rows are written in id order, so
  the rows are sorted by ascending atom id and every per-atom array (positions, types, charges,
  molecule-ids, image flags, and the joined velocities) follows that order, so the arrays line up
  and a data→data round-trip is stable.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO, cast

import numpy as np
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    UserMetadata,
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
from xtalate.sdk.lammps import Box, box_from_edges, resolve_species
from xtalate.sdk.lammps import unit_style as lookup_unit_style
from xtalate.sdk.lammps.units import UnitStyle

FORMAT_ID = "lammps_data"

#: ``custom_global`` — the unit style in force (the recovery-resolved style code). The data
#: exporter (M48-S2) reads it back to write masses/positions/velocities in that basis; the
#: re-parse must reproduce it for the write-side conversion to validate (Part 5 §2).
_UNITS_KEY = "lammps_data:units"
#: ``custom_global`` — the title comment on line 0, carried verbatim so the restart round-trip
#: reproduces it (only when non-empty; a blank title carries no information, P3).
_COMMENT_KEY = "lammps_data:comment"
#: ``custom_global`` — the verbatim topology payload: the body sections with no canonical home
#: (Bonds/Angles/…, every ``* Coeffs``, unrecognized sections, and a ``Masses`` copy only when it
#: holds a declared-but-unused type) plus the header's topology count lines, each a
#: JSON-serializable record of raw rows + comment + order.
_TOPOLOGY_KEY = "lammps_data:topology"
#: ``custom_per_atom`` — the source atom ids, molecule-ids (full only), and numeric types, in the
#: id-sorted order every per-atom array uses. The resolved symbols do not by themselves preserve
#: the source's id/type numbering, so the numbers are carried (P1).
_ID_KEY = "lammps_data:id"
_MOLECULE_KEY = "lammps_data:molecule_id"
_TYPE_KEY = "lammps_data:type"

# Issue codes (Part 3 §5; the recoverable ones carry recovery_hints).
_EMPTY = "LAMMPSDATA_EMPTY"
_ENCODING = "LAMMPSDATA_ENCODING_ERROR"
_MALFORMED = "LAMMPSDATA_MALFORMED"
_AMBIGUOUS_UNITS = "LAMMPSDATA_AMBIGUOUS_UNITS"
_UNSUPPORTED_UNITS = "LAMMPSDATA_UNSUPPORTED_UNITS"
_AMBIGUOUS_ATOM_STYLE = "LAMMPSDATA_AMBIGUOUS_ATOM_STYLE"
_UNSUPPORTED_ATOM_STYLE = "LAMMPSDATA_UNSUPPORTED_ATOM_STYLE"
_MISSING_SPECIES = "LAMMPSDATA_MISSING_SPECIES"
_TOPOLOGY_CARRIED = "LAMMPSDATA_TOPOLOGY_CARRIED"
_UNMAPPED_SECTION_CARRIED = "LAMMPSDATA_UNMAPPED_SECTION_CARRIED"
_IMAGE_FLAGS_CARRIED = "LAMMPSDATA_IMAGE_FLAGS_CARRIED"
_UNITS_INTERPRETED = "LAMMPSDATA_UNITS_INTERPRETED"
_SPECIES_SUPPLIED = "LAMMPSDATA_SPECIES_SUPPLIED"
_ATOM_STYLE_INTERPRETED = "LAMMPSDATA_ATOM_STYLE_INTERPRETED"

_UNITS_HINT = "ambiguous_units"
_SPECIES_HINT = "supply_species"
_ATOM_STYLE_HINT = "ambiguous_atom_style"

#: The atom styles this release supports, and the meaning of each Atoms column *before* any
#: optional trailing ``ix iy iz`` image-flag triple (M48). The layout is the whole of what the
#: style fixes: which column is the charge, which the molecule-id (Part 3 §3).
_STYLE_LAYOUTS: dict[str, tuple[str, ...]] = {
    "atomic": ("id", "type", "x", "y", "z"),
    "charge": ("id", "type", "q", "x", "y", "z"),
    "full": ("id", "molecule", "type", "q", "x", "y", "z"),
}
#: The body sections this parser maps to canonical fields rather than carrying verbatim.
#: ``Atoms``/``Velocities`` interpret their rows; ``Masses`` maps to ``atoms.masses`` (its sole
#: canonical home — the exporter regenerates the section from it, M48-S2), and is carried in the
#: topology payload *only* when it holds information ``atoms.masses`` cannot — a mass for an atom
#: type no atom uses (see ``_parse``). Every *other* section (Bonds/Angles/…, every ``* Coeffs``,
#: and any unrecognized keyword) is carried into the topology payload.
_MAPPED_SECTIONS = frozenset({"Atoms", "Velocities", "Masses"})
#: The standard LAMMPS topology sections — recognized, no canonical home, carried verbatim and
#: covered by the summary ``LAMMPSDATA_TOPOLOGY_CARRIED``. A carried section that is *not* one of
#: these (and not a ``* Coeffs`` block) is genuinely unrecognized and additionally warns
#: ``LAMMPSDATA_UNMAPPED_SECTION_CARRIED`` (Part 3 §3).
_KNOWN_TOPOLOGY_SECTIONS = frozenset(
    {"Bonds", "Angles", "Dihedrals", "Impropers", "Ellipsoids", "Lines", "Triangles", "Bodies"}
)


def _is_known_topology_section(name: str) -> bool:
    """Whether ``name`` is a recognized topology section (a named block or a ``* Coeffs`` table)."""
    return name in _KNOWN_TOPOLOGY_SECTIONS or name.endswith("Coeffs")


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
    """Yield decoded lines off the raw byte stream one at a time (the dump/XDATCAR machinery)."""
    while True:
        raw = stream.readline()
        if raw == b"":
            return
        try:
            yield raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                _ENCODING,
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); lammps_data is a "
                "text format",
            ) from exc


class _Lines:
    """A single-pass line source with one-line push-back (the dump helper, verbatim shape)."""

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
        """The next non-blank, non-comment-only line (rstripped), or ``None`` at end of file.

        A ``#``-only line and a line's trailing ``# …`` are LAMMPS comments; a wholly blank or
        wholly commented line separates sections and is skipped here. A trailing comment on a data
        line is stripped by the row reader, not here (a section keyword's comment carries the atom
        style, so it is handled by the caller)."""
        while (line := self.next()) is not None:
            body = line.split("#", 1)[0]
            if body.strip() != "":
                return line.rstrip("\n")
        return None


def _strip_comment(line: str) -> tuple[str, str | None]:
    """Split a line into its content and trailing ``# comment`` (the comment text, or ``None``)."""
    content, sep, comment = line.partition("#")
    return content.rstrip(), (comment.strip() if sep else None)


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def _as_int(token: str, *, where: str, what: str) -> int:
    try:
        value = float(token)
    except ValueError:
        raise _error(_MALFORMED, f"{where}: expected an integer {what}, found {token!r}") from None
    if value != int(value):
        raise _error(_MALFORMED, f"{where}: expected an integer {what}, found {token!r}")
    return int(value)


@dataclass
class _Header:
    """The numeric header: the atom count, the declared atom-type count, the box, and the verbatim
    topology count lines (every header line that is neither the atom count nor a box line)."""

    n_atoms: int
    n_atom_types: int | None
    box: Box
    topology_counts: list[str]
    # Explicitly records whether the parser had to retain a synthetic ``atom types`` line in
    # ``topology_counts`` for an over-declared type table. The exporter must not rediscover this
    # from line spelling (LOW-DATA4); it is parser state carried with the topology payload.
    atom_types_line_in_counts: bool = False


@dataclass
class _Section:
    """One body section: its keyword, the trailing keyword comment (the atom style for ``Atoms``),
    and its raw data rows (verbatim, comments intact)."""

    name: str
    comment: str | None
    rows: list[str]


def _read_header(lines: _Lines) -> tuple[str, _Header]:
    """Read the title comment (line 0) and the numeric header up to the first section keyword.

    Returns the title comment and the parsed header. The header ends at the first line whose first
    token is not a number (a section keyword); that line is pushed back for the body reader.
    """
    title_raw = lines.next()
    if title_raw is None:
        raise _error(_EMPTY, "file is empty; a LAMMPS data file starts with a title comment line")
    title = title_raw.rstrip("\n").strip()

    n_atoms: int | None = None
    n_atom_types: int | None = None
    atom_types_line_in_counts = False
    box_edges: dict[str, float] = {}
    topology_counts: list[str] = []

    while (line := lines.next_significant()) is not None:
        toks = line.split()
        if not _is_number(toks[0]):
            lines.push(line)  # the first section keyword — header is done
            break
        content, _ = _strip_comment(line)
        toks = content.split()
        tail2 = toks[-2:]
        tail3 = toks[-3:]
        if tail2 == ["xlo", "xhi"]:
            box_edges["xlo"], box_edges["xhi"] = _two_floats(toks, where="xlo xhi line")
        elif tail2 == ["ylo", "yhi"]:
            box_edges["ylo"], box_edges["yhi"] = _two_floats(toks, where="ylo yhi line")
        elif tail2 == ["zlo", "zhi"]:
            box_edges["zlo"], box_edges["zhi"] = _two_floats(toks, where="zlo zhi line")
        elif tail3 == ["xy", "xz", "yz"]:
            box_edges["xy"], box_edges["xz"], box_edges["yz"] = _three_floats(
                toks, where="xy xz yz line"
            )
        elif tail2 == ["atom", "types"]:
            n_atom_types = _as_int(toks[0], where="'atom types' line", what="atom-type count")
        elif toks[-1:] == ["atoms"] and len(toks) == 2:
            n_atoms = _as_int(toks[0], where="'atoms' line", what="atom count")
        else:
            # Any other header count line (bonds/angles/…, their type counts, extra reservations,
            # ellipsoids/lines/triangles/bodies): no canonical home — carried verbatim (P1).
            topology_counts.append(line)

    if n_atoms is None:
        raise _error(_MALFORMED, "header declares no 'atoms' count; a data file must state one")
    if n_atoms <= 0:
        raise _error(_MALFORMED, f"header declares {n_atoms} atoms; a data file needs at least one")
    for edge in ("xlo", "xhi", "ylo", "yhi", "zlo", "zhi"):
        if edge not in box_edges:
            raise _error(
                _MALFORMED,
                f"header is missing the {edge!r} box bound; a data file must state xlo/xhi, "
                "ylo/yhi, zlo/zhi",
            )
    box = box_from_edges(
        box_edges["xlo"],
        box_edges["xhi"],
        box_edges["ylo"],
        box_edges["yhi"],
        box_edges["zlo"],
        box_edges["zhi"],
        xy=box_edges.get("xy", 0.0),
        xz=box_edges.get("xz", 0.0),
        yz=box_edges.get("yz", 0.0),
    )
    return title, _Header(
        n_atoms=n_atoms,
        n_atom_types=n_atom_types,
        box=box,
        topology_counts=topology_counts,
        atom_types_line_in_counts=atom_types_line_in_counts,
    )


def _two_floats(toks: list[str], *, where: str) -> tuple[float, float]:
    try:
        return float(toks[0]), float(toks[1])
    except (ValueError, IndexError):
        raise _error(
            _MALFORMED, f"{where}: expected two numeric bounds, found {' '.join(toks)!r}"
        ) from None


def _three_floats(toks: list[str], *, where: str) -> tuple[float, float, float]:
    try:
        return float(toks[0]), float(toks[1]), float(toks[2])
    except (ValueError, IndexError):
        raise _error(
            _MALFORMED, f"{where}: expected three numeric tilts, found {' '.join(toks)!r}"
        ) from None


def _read_sections(lines: _Lines) -> list[_Section]:
    """Read every body section: a keyword line, then the rows whose first token is an integer.

    A section keyword opens a section; the data rows are every following non-blank line whose first
    token is an integer index; the next section keyword (first token not a number) ends it and is
    pushed back. Rows are kept verbatim (comments intact) — the mapped sections interpret them,
    the carried ones reproduce them.
    """
    sections: list[_Section] = []
    while (line := lines.next_significant()) is not None:
        toks = line.split()
        if _is_number(toks[0]):
            raise _error(
                _MALFORMED,
                f"data row {line.strip()!r} appears outside any section (no section keyword "
                "preceded it)",
            )
        content, comment = _strip_comment(line)
        name = content.strip()
        rows: list[str] = []
        while (row := lines.next_significant()) is not None:
            if _is_number(row.split()[0]):
                rows.append(row)
            else:
                lines.push(row)  # the next section keyword
                break
        sections.append(_Section(name=name, comment=comment, rows=rows))
    return sections


def _resolve_atom_style(atoms_section: _Section, *, override: str | None) -> str:
    """The atom style in force: the ``Atoms # <style>`` comment, or a recovery override.

    A supported style comment is used directly. An *unsupported* style comment refuses (it is data
    the release cannot interpret, not an ambiguity to resolve). No comment and no override raises
    the recoverable ``ambiguous_atom_style`` — the caller must name atomic/charge/full. An override
    is only consulted when the file itself is silent; a file that declares its style is never
    overridden (the declaration is genuine source data).
    """
    declared = atoms_section.comment.strip() if atoms_section.comment else None
    if declared:
        # A comment like "full" names the style; a longer comment's first token is the style
        # (LAMMPS writes exactly "Atoms # <style>").
        style = declared.split()[0]
        if style not in _STYLE_LAYOUTS:
            raise _error(
                _UNSUPPORTED_ATOM_STYLE,
                f"the Atoms section declares atom style {style!r}, which this release does not "
                f"support (atomic/charge/full only, M48); the column layout cannot be interpreted",
                location="Atoms section",
            )
        if override is not None and override != style:
            raise _error(
                _MALFORMED,
                f"the Atoms section declares atom style {style!r} but a recovery override asked "
                f"for {override!r}; a file that declares its style is not overridden",
                location="Atoms section",
            )
        return style
    if override is not None:
        if override not in _STYLE_LAYOUTS:
            raise _error(
                _UNSUPPORTED_ATOM_STYLE,
                f"ambiguous_atom_style cannot apply unsupported style {override!r} "
                "(atomic/charge/full only)",
            )
        return override
    raise _error(
        _AMBIGUOUS_ATOM_STYLE,
        "the Atoms section carries no '# <style>' comment, so the column layout (which column is "
        "the charge, which the molecule-id) is unknowable; name the atom style (atomic/charge/"
        "full) — never guessed (R3)",
        location="Atoms section",
        hint=_ATOM_STYLE_HINT,
    )


def _parse_atom_rows(
    section: _Section, style: str, n_atoms: int
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Parse the ``Atoms`` rows under ``style`` into an id-sorted order plus per-column arrays.

    Returns the ascending sort order (by atom id) and a dict of raw (un-unit-converted) columns:
    ``id`` and ``type`` always; ``molecule`` for full; ``q`` for charge/full; ``x``/``y``/``z``
    always; ``ix``/``iy``/``iz`` when a complete trailing image-flag triple is present. Every array
    is already in the sorted order.
    """
    layout = _STYLE_LAYOUTS[style]
    base = len(layout)
    if len(section.rows) != n_atoms:
        raise _error(
            _MALFORMED,
            f"the header declares {n_atoms} atoms but the Atoms section has {len(section.rows)} "
            "rows",
            location="Atoms section",
        )
    has_image = False
    parsed: list[list[float]] = []
    for r, raw in enumerate(section.rows):
        content, _ = _strip_comment(raw)
        toks = content.split()
        if len(toks) == base + 3:
            row_has_image = True
        elif len(toks) == base:
            row_has_image = False
        else:
            raise _error(
                _MALFORMED,
                f"Atoms row {r} has {len(toks)} columns; atom style {style!r} needs {base} "
                f"(or {base + 3} with trailing image flags): {raw.strip()!r}",
                location="Atoms section",
            )
        if r == 0:
            has_image = row_has_image
        elif row_has_image != has_image:
            raise _error(
                _MALFORMED,
                f"Atoms row {r} {'has' if row_has_image else 'lacks'} image flags but row 0 does "
                "not match; the image-flag triple must be present on every atom or none",
                location="Atoms section",
            )
        try:
            parsed.append([float(t) for t in toks])
        except ValueError:
            raise _error(
                _MALFORMED,
                f"Atoms row {r} has a non-numeric value: {raw.strip()!r}",
                location="Atoms section",
            ) from None
    data = np.asarray(parsed, dtype=np.float64)

    id_index = layout.index("id")
    ids_float = data[:, id_index]
    if not np.all(ids_float == np.floor(ids_float)):
        raise _error(
            _MALFORMED, "the Atoms 'id' column holds non-integer values", location="Atoms section"
        )
    order = np.argsort(ids_float, kind="stable")
    data = data[order]
    ids_sorted = data[:, id_index].astype(np.int64)
    if ids_sorted.size > 1 and np.any(np.diff(ids_sorted) == 0):
        raise _error(
            _MALFORMED,
            "the Atoms section repeats an atom id; ids must be unique",
            location="Atoms section",
        )

    columns: dict[str, np.ndarray] = {}
    for name in layout:
        columns[name] = data[:, layout.index(name)]
    if has_image:
        columns["ix"] = data[:, base]
        columns["iy"] = data[:, base + 1]
        columns["iz"] = data[:, base + 2]
    return order, columns


def _parse_masses(section: _Section) -> dict[int, float]:
    """Parse a ``Masses`` section into a type → mass (in the style's mass unit) map. Comments (the
    ``# element`` LAMMPS writes) are ignored for the mapping — the raw section is carried
    separately for restart fidelity."""
    table: dict[int, float] = {}
    for raw in section.rows:
        content, _ = _strip_comment(raw)
        toks = content.split()
        if len(toks) != 2:
            raise _error(
                _MALFORMED,
                f"Masses row {raw.strip()!r} must be '<type> <mass>'",
                location="Masses section",
            )
        type_id = _as_int(toks[0], where="Masses section", what="atom type")
        try:
            table[type_id] = float(toks[1])
        except ValueError:
            raise _error(
                _MALFORMED,
                f"Masses row {raw.strip()!r} has a non-numeric mass",
                location="Masses section",
            ) from None
    return table


def _parse_velocities(section: _Section, ids_sorted: np.ndarray) -> np.ndarray:
    """Parse a ``Velocities`` section (``id vx vy vz``) and reorder it to the atoms' id-sorted
    order. The velocity ids must be exactly the atom ids — a mismatch is a malformed file, never
    silently trimmed or padded."""
    by_id: dict[int, tuple[float, float, float]] = {}
    for raw in section.rows:
        content, _ = _strip_comment(raw)
        toks = content.split()
        if len(toks) != 4:
            raise _error(
                _MALFORMED,
                f"Velocities row {raw.strip()!r} must be '<id> vx vy vz'",
                location="Velocities section",
            )
        vid = _as_int(toks[0], where="Velocities section", what="atom id")
        try:
            by_id[vid] = (float(toks[1]), float(toks[2]), float(toks[3]))
        except ValueError:
            raise _error(
                _MALFORMED,
                f"Velocities row {raw.strip()!r} has a non-numeric value",
                location="Velocities section",
            ) from None
    if set(by_id) != {int(i) for i in ids_sorted}:
        raise _error(
            _MALFORMED,
            "the Velocities section's atom ids do not match the Atoms section's ids; every atom "
            "must have exactly one velocity",
            location="Velocities section",
        )
    return np.asarray([by_id[int(i)] for i in ids_sorted], dtype=np.float64)


def _build_topology(
    header: _Header, sections: list[_Section], *, extra_masses: _Section | None
) -> tuple[dict[str, object] | None, list[ParseIssue]]:
    """Assemble the verbatim topology payload and its warnings.

    The payload holds the header's topology count lines and every body section that has no
    canonical home (Bonds/Angles/…, ``* Coeffs``, unrecognized keywords), each as raw rows +
    comment, in file order. ``extra_masses`` is the ``Masses`` section, included **only** when it
    holds a mass ``atoms.masses`` cannot (a declared-but-unused atom type); in the ordinary case
    masses live solely in ``atoms.masses`` and the exporter regenerates the section. A recognized
    topology section is covered by the summary ``LAMMPSDATA_TOPOLOGY_CARRIED``; an *unrecognized*
    keyword additionally warns ``LAMMPSDATA_UNMAPPED_SECTION_CARRIED``. Returns ``None`` when there
    is nothing to carry.
    """
    issues: list[ParseIssue] = []
    carried: list[dict[str, object]] = []
    for section in sections:
        if section.name in _MAPPED_SECTIONS:
            continue  # Atoms/Velocities interpreted; Masses carried only via extra_masses
        carried.append(
            {"section": section.name, "comment": section.comment, "rows": list(section.rows)}
        )
        if not _is_known_topology_section(section.name):
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=_UNMAPPED_SECTION_CARRIED,
                    message=(
                        f"section {section.name!r} is not a recognized LAMMPS section; its "
                        f"{len(section.rows)} row(s) are carried verbatim in "
                        f"user_metadata.custom_global['{_TOPOLOGY_KEY}'] and are dropped by any "
                        "cross-format conversion (Part 3 §3)"
                    ),
                    location=f"{section.name} section",
                )
            )
    if extra_masses is not None:
        carried.append(
            {
                "section": "Masses",
                "comment": extra_masses.comment,
                "rows": list(extra_masses.rows),
            }
        )
    if not carried and not header.topology_counts:
        return None, issues
    payload: dict[str, object] = {
        "header_counts": list(header.topology_counts),
        "sections": carried,
        # Keep the numeric declaration and the exact placement state explicit. The exporter
        # uses these parser facts to reconstruct the header; it must not infer them from a
        # free-form line spelling (LOW-DATA4).
        "declared_atom_types": header.n_atom_types,
        "atom_types_line_in_counts": header.atom_types_line_in_counts,
    }
    issues.append(
        ParseIssue(
            severity="warning",
            code=_TOPOLOGY_CARRIED,
            message=(
                "topology (bonds/angles/dihedrals/impropers and force-field coefficients) has no "
                "canonical representation; it is carried verbatim in "
                f"user_metadata.custom_global['{_TOPOLOGY_KEY}'] so a LAMMPS-data→LAMMPS-data "
                "conversion preserves it, and is dropped (with this record) by any other target"
            ),
        )
    )
    return payload, issues


class LammpsDataParser(ParserPlugin):
    """LAMMPS data / restart reader (Part 3 §3; M48-S1)."""

    version = "0.1.0"

    def __init__(self) -> None:
        self.format_id = FORMAT_ID
        self.format_name = "LAMMPS data (configuration/restart)"
        self.file_extensions = (".data", ".lmp", ".lammps")

    # -- sniff -------------------------------------------------------------------------

    def sniff(self, head: bytes, filename: str | None) -> float:
        # A data file has no magic first line (line 0 is a free-text title), but its box header
        # is highly specific: a line ending in "xlo xhi" appears in no other Phase-1/LAMMPS text
        # format (a dump writes "ITEM: BOX BOUNDS"). The extension is a hint only, never decisive.
        for line in head.split(b"\n"):
            if line.rstrip().endswith(b"xlo xhi"):
                return 0.95
        return 0.0

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read; refuses (recoverably) on the first fact a data file never states."""
        return self._parse(
            stream,
            filename=filename,
            unit_style=None,
            species_map=None,
            reference_symbols=None,
            atom_style=None,
        )

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
        """Re-read under one or more parse-time recovery choices (Part 4 §3.3; M48).

        A data file needs up to three parse-time facts at once (``ambiguous_units`` +
        ``missing_species`` + ``ambiguous_atom_style``), so this consumes ``recovery_context`` —
        the accumulated ``{scenario: {"choice", "parameters"}}`` map the orchestrator threads
        through each re-read (the M48 SDK seam). It applies **every** resolved choice present, then
        re-parses; any still-unresolved fact raises its own recoverable ``ParseError`` and the
        orchestrator loops. Each applied choice is recorded with a warning ``ParseIssue`` (P1).
        """
        context: dict[str, dict[str, object]] = {}
        if recovery_context:
            context.update(cast("dict[str, dict[str, object]]", dict(recovery_context)))
        # Fold in the current call's choice too, so a caller that drives parse_recover directly
        # (not through the accumulating orchestrator) still applies this one.
        scenario = {
            _UNITS_HINT: "ambiguous_units",
            _SPECIES_HINT: "missing_species",
            _ATOM_STYLE_HINT: "ambiguous_atom_style",
        }.get(hint)
        if scenario is not None:
            context[scenario] = {"choice": choice, "parameters": parameters}

        unit_style, units_note = self._units_from_context(context)
        species_map, reference_symbols, species_note = self._species_from_context(context)
        atom_style, style_note = self._atom_style_from_context(context)

        result = self._parse(
            stream,
            filename=filename,
            unit_style=unit_style,
            species_map=species_map,
            reference_symbols=reference_symbols,
            atom_style=atom_style,
        )
        notes = [n for n in (style_note, units_note, species_note) if n is not None]
        return ParseResult(canonical=result.canonical, issues=[*result.issues, *notes])

    def _units_from_context(
        self, context: dict[str, dict[str, object]]
    ) -> tuple[UnitStyle | None, ParseIssue | None]:
        spec = context.get("ambiguous_units")
        if spec is None:
            return None, None
        code = spec.get("choice")
        style = lookup_unit_style(code) if isinstance(code, str) else None
        if style is None:
            raise _error(
                _UNSUPPORTED_UNITS,
                f"parse_recover(ambiguous_units) cannot apply unknown style {code!r}",
            )
        note = ParseIssue(
            severity="warning",
            code=_UNITS_INTERPRETED,
            message=(
                f"unit style interpreted as {code} ({style.summary}) per recovery choice; all "
                "positions, velocities, box bounds, and masses converted from that basis"
            ),
        )
        return style, note

    def _species_from_context(
        self, context: dict[str, dict[str, object]]
    ) -> tuple[Mapping[int, str] | list[str] | None, list[str] | None, ParseIssue | None]:
        spec = context.get("missing_species")
        if spec is None:
            return None, None, None
        code = spec.get("choice")
        params = spec.get("parameters")
        parameters = cast("dict[str, object]", params) if isinstance(params, dict) else {}
        if code == "species_map":
            wording = "a type→symbol species_map preset"
            return _recover_species_map(parameters), None, _species_note(code, wording)
        if code == "upload_reference":
            wording = "the per-atom symbols of a matching reference structure"
            return None, _reference_symbols(parameters), _species_note(code, wording)
        raise _error(
            _MISSING_SPECIES,
            f"supply_species has no choice {code!r} (offered: species_map, upload_reference)",
            hint=_SPECIES_HINT,
        )

    def _atom_style_from_context(
        self, context: dict[str, dict[str, object]]
    ) -> tuple[str | None, ParseIssue | None]:
        spec = context.get("ambiguous_atom_style")
        if spec is None:
            return None, None
        code = spec.get("choice")
        if not isinstance(code, str) or code not in _STYLE_LAYOUTS:
            raise _error(
                _UNSUPPORTED_ATOM_STYLE,
                f"ambiguous_atom_style cannot apply unsupported style {code!r} "
                "(atomic/charge/full only)",
            )
        note = ParseIssue(
            severity="warning",
            code=_ATOM_STYLE_INTERPRETED,
            message=(
                f"Atoms columns interpreted as atom style {code} "
                f"({' '.join(_STYLE_LAYOUTS[code])}) per recovery choice; the file's Atoms section "
                "named no style"
            ),
        )
        return code, note

    def supports_streaming(self) -> bool:
        return False  # a data file is a single configuration — no per-frame streaming benefit

    def _parse(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        unit_style: UnitStyle | None,
        species_map: Mapping[int, str] | list[str] | None,
        reference_symbols: list[str] | None,
        atom_style: str | None,
    ) -> ParseResult:
        """The one read path (ordinary parse and every recovery re-read). Refuses in dependency
        order: atom style (needed to read the columns) → units (needed to convert) → species
        (needed to name atoms)."""
        issues: list[ParseIssue] = []
        lines = _Lines(stream)
        title, header = _read_header(lines)
        sections = _read_sections(lines)

        by_name = {s.name: s for s in sections}
        atoms_section = by_name.get("Atoms")
        if atoms_section is None:
            raise _error(_MALFORMED, "the file has no Atoms section")

        # 1. Atom style (needed before the Atoms columns can be read at all).
        style = _resolve_atom_style(atoms_section, override=atom_style)
        layout = _STYLE_LAYOUTS[style]
        _, columns = _parse_atom_rows(atoms_section, style, header.n_atoms)

        # 2. Unit style (needed to convert positions/velocities/box/masses to canonical Å/fs/eV).
        if unit_style is None:
            raise _error(
                _AMBIGUOUS_UNITS,
                "no unit style declared (a data file never states one); every position, velocity, "
                "box bound, and mass is uninterpretable until the style is known — refuse, never "
                "guess (R3)",
                hint=_UNITS_HINT,
            )
        distance = unit_style.distance_to_angstrom

        # 3. Species (a data file lists numeric types only; symbols are always recovered).
        types_float = columns["type"]
        if not np.all(types_float == np.floor(types_float)):
            raise _error(
                _MALFORMED,
                "the Atoms 'type' column holds non-integer values",
                location="Atoms section",
            )
        int_types = types_float.astype(np.int64)
        symbols = self._resolve_symbols(int_types, species_map, reference_symbols, header.n_atoms)

        positions = np.column_stack([columns["x"], columns["y"], columns["z"]]) * distance
        # A data file writes actual Cartesian coordinates (possibly outside the box); the box
        # origin is the lattice origin, so canonical positions are the coordinates as written,
        # unit-converted (no origin shift — unlike a wrapped dump, image flags carry the wrapping).
        lattice = header.box.lattice * distance

        charges: np.ndarray | None = None
        if "q" in layout:
            charges = columns["q"]

        atom_ids = columns["id"].astype(np.int64)
        velocities: np.ndarray | None = None
        velocities_section = by_name.get("Velocities")
        if velocities_section is not None:
            velocities = (
                _parse_velocities(velocities_section, atom_ids)
                * unit_style.velocity_to_angstrom_per_femtosecond
            )

        # Masses map to the portable per-atom atoms.masses (amu) — its sole canonical home; the
        # exporter regenerates the section from it (M48-S2). The raw section is carried in the
        # topology payload only when it holds a mass atoms.masses cannot express — one for a
        # declared atom type that no atom uses (extra_masses below); the ordinary section is fully
        # reconstructed from atoms.masses and is not carried, so a mass-only file reports no
        # topology loss.
        masses: np.ndarray | None = None
        extra_masses: _Section | None = None
        masses_section = by_name.get("Masses")
        used_types = {int(t) for t in int_types}
        if masses_section is not None:
            table = _parse_masses(masses_section)
            missing = sorted(used_types - set(table))
            if missing:
                raise _error(
                    _MALFORMED,
                    f"the Masses section has no mass for atom type(s) {missing}",
                    location="Masses section",
                )
            masses = np.asarray(
                [table[int(t)] * unit_style.mass_to_amu for t in int_types], dtype=np.float64
            )
            unused = set(table) - used_types
            declared = header.n_atom_types
            over_declared = declared is not None and declared > len(used_types)
            if unused or over_declared:
                extra_masses = masses_section
                if over_declared:
                    # Keep the existing byte-order caveat explicit: this synthetic line is
                    # appended with the carried topology counts rather than reconstructed among
                    # the original header lines. The exporter receives the flag below instead of
                    # using a fragile string heuristic (LOW-DATA3/4).
                    header.topology_counts.append(f"{header.n_atom_types} atom types")
                    header.atom_types_line_in_counts = True

        # Per-atom carries (id-sorted order): id + type always, molecule-id for full, and the
        # named image-flag payload when a complete ix/iy/iz triple was present.
        custom_per_atom: dict[str, object] = {
            _ID_KEY: atom_ids,
            _TYPE_KEY: int_types,
        }
        if "molecule" in layout:
            custom_per_atom[_MOLECULE_KEY] = columns["molecule"].astype(np.int64)
        if "ix" in columns:
            custom_per_atom[IMAGE_FLAGS_CARRY_KEY] = np.column_stack(
                [columns["ix"], columns["iy"], columns["iz"]]
            ).astype(np.int64)
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=_IMAGE_FLAGS_CARRIED,
                    message=(
                        "per-atom image flags (ix/iy/iz) carried to "
                        f"user_metadata.custom_per_atom[{IMAGE_FLAGS_CARRY_KEY!r}]; coordinates "
                        "are wrapped Cartesian. The flags are never applied on parse (D43); a "
                        "target that cannot hold them loses the unwrapping, which pre-flight sees."
                    ),
                    location="Atoms section",
                )
            )

        topology, topology_issues = _build_topology(header, sections, extra_masses=extra_masses)
        issues.extend(topology_issues)

        custom_global: dict[str, object] = {_UNITS_KEY: unit_style.code}
        if title:
            custom_global[_COMMENT_KEY] = title
        if topology is not None:
            custom_global[_TOPOLOGY_KEY] = topology

        parse_notes = [
            f"Unit style in force: {unit_style.code} ({unit_style.summary}) — applied by recovery "
            "(a data file declares no unit style).",
            "pbc not declared in a data file (LAMMPS reads the boundary from the input script's "
            "`boundary` command, not the file); a simulation box is periodic by the format's "
            "nature, so cell.pbc was set to the LAMMPS default (p p p) — applied and recorded "
            "here, not read from the file.",
            f"Atom style: {style} ({' '.join(layout)}).",
        ]
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={
                "positions": _units_distance(unit_style),
                "lattice_vectors": _units_distance(unit_style),
                "velocities": _units_velocity(unit_style),
                "masses": "amu",
            },
            parse_notes=parse_notes,
        )
        frame = Frame(
            index=0,
            atoms=AtomsBlock(symbols=symbols, positions=positions, masses=masses),
            cell=Cell(lattice_vectors=lattice, pbc=(True, True, True)),
            dynamics=Dynamics(velocities=velocities),
            electronic=Electronic(charges=charges),
        )
        canonical = CanonicalObject(
            frames=[frame],
            trajectory=None,  # a data file is a single configuration, no time axis (§3.2)
            provenance=provenance,
            user_metadata=UserMetadata(
                custom_global=cast("dict[str, JsonValue]", custom_global),
                custom_per_atom=cast("dict[str, Any]", custom_per_atom),
            ),
        )
        return ParseResult(canonical=canonical, issues=issues)

    def _resolve_symbols(
        self,
        int_types: np.ndarray,
        species_map: Mapping[int, str] | list[str] | None,
        reference_symbols: list[str] | None,
        n_atoms: int,
    ) -> list[str]:
        """Numeric atom types → element symbols, via a ``species_map`` preset or an
        ``upload_reference`` structure's per-atom symbols (the ``missing_species`` case, Part 3
        §7.2). Refuses recoverably when neither is supplied."""
        if reference_symbols is not None:
            if len(reference_symbols) != n_atoms:
                raise _error(
                    _MISSING_SPECIES,
                    f"the file has {n_atoms} atoms but the reference structure supplies "
                    f"{len(reference_symbols)} per-atom symbols; the reference does not match",
                    hint=_SPECIES_HINT,
                )
            try:
                return resolve_species(
                    type_values=None, element_column=list(reference_symbols), species_map=None
                )
            except ValueError as exc:
                raise _error(_MALFORMED, str(exc)) from exc
        if species_map is None:
            raise _error(
                _MISSING_SPECIES,
                "the Atoms section lists numeric atom types but no species_map preset was "
                "supplied; symbols are required and did not exist in the file (Part 2 §3.3)",
                hint=_SPECIES_HINT,
            )
        try:
            return resolve_species(
                type_values=int_types, element_column=None, species_map=species_map
            )
        except ValueError as exc:
            raise _error(_MALFORMED, str(exc)) from exc

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
                        "A data file lists numeric atom types only; symbols resolve through the "
                        "missing_species recovery (species_map / upload_reference), never guessed."
                    ),
                ),
                "atoms.positions": full,
                "atoms.masses": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="From the Masses table (per type), converted to amu; None if absent.",
                ),
                "cell.lattice_vectors": full,
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Not stated in a data file; set to the LAMMPS p-p-p default, recorded.",
                ),
                "dynamics.velocities": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only when a Velocities section is present; unit-converted.",
                ),
                "electronic.charges": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="From the charge column of the charge/full atom styles.",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Topology (bonds/angles/coeffs/…) and the title carried verbatim.",
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Atom ids, molecule-ids (full), numeric types, and image flags.",
                ),
            },
            max_frames=1,  # a single configuration
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="cartesian",
            lossy_notes=[],
            # The named image-flag capability dimension (M46-S3, D176): a data file reads a
            # complete ix/iy/iz triple specifically, so the pre-flight can predict the unwrapping
            # loss when such a source targets a format that cannot hold them.
            holds_image_flags=True,
        )


def _species_note(code: str, wording: str) -> ParseIssue:
    return ParseIssue(
        severity="warning",
        code=_SPECIES_SUPPLIED,
        message=(
            f"element symbols supplied via recovery choice {code!r} ({wording}); the source data "
            "file listed only numeric atom types"
        ),
    )


def _recover_species_map(parameters: dict[str, object]) -> Mapping[int, str] | list[str]:
    """Parse the ``species_map`` choice's ``species`` parameter (Part 4 §3.3): a dict or ordered
    list passes through; the CLI string form (``"1:Si 2:O"`` — type:symbol pairs) is split into a
    mapping. Commas are tolerated too (``"1:Si,2:O"``). Shared shape with the dump parser."""
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
        "species_map needs a 'species' parameter (a type→symbol map, an ordered symbol list, or "
        "'1:Si 2:O')",
        hint=_SPECIES_HINT,
    )


def _reference_symbols(parameters: dict[str, object]) -> list[str]:
    """The per-atom symbols for the ``upload_reference`` choice, from a matching reference
    structure's frame-0 symbols (Part 4 §3.3; the CLI injects a parsed ``reference`` object). Shared
    shape with the dump parser."""
    ref = parameters.get("reference")
    if ref is None:
        raise _error(
            _MISSING_SPECIES,
            "upload_reference needs a 'reference' parameter (the parsed reference structure); pass "
            "--recover missing_species=upload_reference,file=PATH",
            hint=_SPECIES_HINT,
        )
    reference = cast(CanonicalObject, ref)
    return [str(s) for s in reference.frames[0].atoms.symbols]


def _units_distance(style: UnitStyle) -> str:
    return {"metal": "angstrom", "real": "angstrom", "si": "meter"}[style.code]


def _units_velocity(style: UnitStyle) -> str:
    return {"metal": "angstrom/picosecond", "real": "angstrom/femtosecond", "si": "meter/second"}[
        style.code
    ]


def make_lammps_data_parser() -> LammpsDataParser:
    return LammpsDataParser()
