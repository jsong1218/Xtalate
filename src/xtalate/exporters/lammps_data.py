"""LAMMPS data (configuration / restart) exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v1.3 M48-S2,
D181).

The write side of the restart format, the exact inverse of ``parsers.lammps_data`` (M48-S1): it
turns a single-configuration Canonical Object back into the text ``data`` file a LAMMPS run reads
with ``read_data``. This is the "restart flagship" — the deploy arrow of the version's
train→deploy→produce→relabel loop — so every mapping is honest and every augmentation reported:

* **Units run through the shared core in the inverse direction, and the write refuses without a
  resolved style.** The canonical model is fixed in Å/fs/eV; a data file declares no unit system,
  so the output only means something once a style is named. The write-side ``ambiguous_units``
  refusal is earned **for free** from ``requires_units_style=True`` (the M47-S1 generalization): the
  pre-flight diff refuses ``canonical → lammps_data`` with no preset and threads the resolved style
  to this exporter under ``custom_global['lammps_data:units']``. Positions, box edges, velocities,
  and masses are converted from the canonical basis to that style by the inverse of M46's
  ``sdk.lammps.units`` factors (charge is unit-independent in the styles this release supports, so
  it is written as-is — the parser reads it the same way). Without a resolved style there is **no**
  write (**P4**).
* **An element column becomes a generated type map.** A data file identifies atoms by numeric
  ``type`` only; the canonical object carries element symbols. The exporter assigns deterministic
  numeric types by first appearance (Si=1, O=2, … in first-seen order, so a round-trip is stable)
  and records the mapping as an export warning — the audit line in the Conversion Report, never a
  silent renumbering. When the object was *read from a data file* and carries a verbatim ``Masses``
  section (a declared-but-unused atom type S1 could not fold into ``atoms.masses``), the source's
  own type numbering is preserved instead, so that carried section stays consistent with the
  ``Atoms`` rows.
* **Masses from the canonical object, or a refusal.** ``atoms.masses`` (amu) is written back as the
  per-type ``Masses`` table, divided by the style's mass factor. A data file *requires* masses, so
  ``atoms.masses`` is a write ``required_field``: an object without them is refused via the existing
  ``missing_masses`` scenario (``standard_masses`` / ``manual_input``) — masses are never invented
  silently (**P4**).
* **Velocities only when present (P3).** The ``Velocities`` section is written only when the frame
  carries ``dynamics.velocities`` — an absent block stays absent, never a zero-filled rest state.
* **Topology carried back byte-faithfully.** ``Bonds``/``Angles``/``Dihedrals``/``Impropers``, every
  ``* Coeffs`` block, unrecognized sections, and the header's topology count lines are reconstructed
  verbatim from ``custom_global['lammps_data:topology']`` (M48-S1's carry), so a data→data
  conversion restores topology byte-for-byte. ``writable_custom_keys`` declares the topology key
  (and the units/comment/per-atom carries), so the pre-flight diff predicts **no** topology loss for
  data→data while every other target predicts it (P1/P5). When the object carries no topology, no
  such sections are written.
* **Restricted triclinic boxes written through the M46 core in reverse.** The canonical lattice
  (restricted triclinic form) is read off to the data file's ``xlo xhi`` … / ``xy xz yz`` edge
  lines by :func:`sdk.lammps.edges_from_box` — the direct inverse of the parser's ``box_from_edges``
  (a data file writes edge parameters directly, unlike a dump's bounding box). A lattice outside the
  restricted form is **refused** (``unrepresentable``), never silently rotated.
* **A single configuration only.** A data file is one frame. A multi-frame (trajectory) object
  cannot be one data file, so ``unrepresentable`` (D179) refuses it — the engine returns a clean
  ``UNREPRESENTABLE_VALUE`` refused report rather than silently writing only frame 0.

**Streaming-first for one-code-path honesty, but single-block.** Mirroring ``lammps_dump`` and
``xdatcar``, ``export`` is defined over ``export_stream``; but a data file is one configuration, so
``export_stream`` asserts exactly one frame and writes a single block. Dump-as-target routes through
the materialized ``convert`` because the write needs the ``ambiguous_units`` recovery resolved
before a byte is written (``requires_units_style``); the same holds here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

import numpy as np

from xtalate.sdk import (
    IMAGE_FLAGS_CARRY_KEY,
    CapabilityLevel,
    ExporterPlugin,
    ExporterWarning,
    FieldCapability,
    FormatCapabilities,
    StreamFrame,
    StreamHeader,
    stream_of,
)
from xtalate.sdk.lammps import edges_from_box, unit_style
from xtalate.sdk.lammps.units import UnitStyle

FORMAT_ID = "lammps_data"

# The custom_global keys the parser carries and this exporter writes back (M48-S1 spellings). The
# units key is placed by the write-side recovery resolver (requires_units_style); the comment is
# the title line; the topology payload is the verbatim carry a data→data round-trip restores.
_UNITS_KEY = "lammps_data:units"
_COMMENT_KEY = "lammps_data:comment"
_TOPOLOGY_KEY = "lammps_data:topology"
# The per-atom carries: source atom ids, molecule-ids (full style), and numeric types, plus the
# shared image-flag carry. All ride in the parser's id-sorted order.
_ID_KEY = "lammps_data:id"
_MOLECULE_KEY = "lammps_data:molecule_id"
_TYPE_KEY = "lammps_data:type"

#: Audit-line code for the generated (or preserved) type map — surfaced in the Conversion Report via
#: ``export_warnings``, the exporter-owned report channel (mirrors the dump exporter's discipline).
_TYPES_ASSIGNED = "LAMMPSDATA_TYPES_ASSIGNED"

#: The three atom styles this release writes, and their column layout *before* any trailing image
#: flags — the exact inverse of the parser's ``_STYLE_LAYOUTS`` (M48-S1).
_STYLE_LAYOUTS: dict[str, tuple[str, ...]] = {
    "atomic": ("id", "type", "x", "y", "z"),
    "charge": ("id", "type", "q", "x", "y", "z"),
    "full": ("id", "molecule", "type", "q", "x", "y", "z"),
}


class LammpsDataExporter(ExporterPlugin):
    """LAMMPS data / restart writer (Part 3 §3; M48-S2)."""

    format_id = FORMAT_ID
    format_name = "LAMMPS data (configuration/restart)"
    version = "0.1.0"

    def export(self, canonical: Any, stream: BinaryIO) -> None:
        """Whole-file write, defined as the streamed write over the object's own frames — so a
        streamed and a materialized export are one code path and cannot diverge (D56)."""
        frame_stream = stream_of(canonical)
        self.export_stream(frame_stream.header, frame_stream.frames(), stream)

    def supports_streaming(self) -> bool:
        # A data file is a single configuration; there is no per-frame streaming benefit, and a
        # multi-frame object is refused (unrepresentable), so this is never a streaming target.
        return False

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        style = self._resolved_style(header)
        collected = list(frames)
        if len(collected) != 1:
            # The engine consults `unrepresentable` and refuses a multi-frame object before export,
            # so this only fires if that guard is ever bypassed — a defensive backstop, not the
            # user-facing path (which returns a clean UNREPRESENTABLE_VALUE report).
            raise ValueError(
                "lammps_data: a data file is a single configuration but the object being exported "
                f"has {len(collected)} frames; refuse a multi-frame object via unrepresentable "
                "rather than writing only one"
            )
        _write_block(stream, collected[0].frame, header, style)

    def export_warnings(self, canonical: Any) -> list[ExporterWarning]:
        """The one transformation this exporter applies that must be audited: it maps element
        symbols to LAMMPS numeric types. The mapping is stated in the Conversion Report as an audit
        line — deterministic first-appearance order, or the source's own numbering when a verbatim
        ``Masses`` section pins it (P1). Built over the single frame the write uses, so the reported
        map is exactly the one written."""
        frame = canonical.frames[0]
        header = stream_of(canonical).header
        symbols = list(frame.atoms.symbols)
        _types, type_map, preserved = _type_numbering(header, symbols)
        mapping = ", ".join(f"type {number} → {symbol}" for symbol, number in type_map.items())
        verb = "Preserved source" if preserved else "Assigned"
        order = "" if preserved else " by first appearance"
        return [
            ExporterWarning(
                code=_TYPES_ASSIGNED,
                message=(
                    f"{verb} LAMMPS atom types{order}: "
                    f"{mapping or 'none (the object has no atoms)'}."
                ),
            )
        ]

    def unrepresentable(self, canonical: Any) -> str | None:
        """Why a data file cannot express ``canonical``'s *values*, or ``None`` when it can (Part 4
        §1; D179). A returned string produces a clean ``UNREPRESENTABLE_VALUE`` refusal, not an
        export-time crash (P1). Four value-level facts the field-granular Capability Matrix cannot
        see are checked here, before export:

        1. **More than one frame.** A data file is one configuration; a trajectory object cannot be
           one data file, and writing only frame 0 would be a silent truncation.
        2. **A general (non-restricted) triclinic cell.** A data file states only the restricted
           triclinic form (``a`` along x, ``b`` in the xy-plane); any other cell would need a
           rotation to write, silently changing the frame of reference (D43). A frame with no
           lattice is a required-field gap the ``missing_lattice`` recovery handles, not this
           method's concern.
        3. **A molecule-id without charges.** The only style that carries a molecule-id is ``full``
           (``id molecule type q x y z``), which also requires a charge column. An object with a
           carried molecule-id but no ``electronic.charges`` has no supported style, and fabricating
           a zero charge (P3) or silently dropping the molecule-id (P1) are both refused.
        4. **One element symbol with more than one mass.** A data file's ``Masses`` table is keyed
           by atom *type*, and types are assigned per element symbol, so all atoms of one symbol
           share a single mass. An object whose atoms of the same symbol carry different masses
           (e.g. isotope labels sharing an element symbol) cannot be expressed without collapsing
           that distinction,
           which the format cannot record — so it is refused rather than silently flattened."""
        frames = canonical.frames
        if len(frames) > 1:
            return (
                f"lammps_data: a data file is a single configuration but the object has "
                f"{len(frames)} frames; a data file cannot hold a trajectory, and writing only "
                "frame 0 would silently drop the rest"
            )
        frame = frames[0]
        cell = frame.cell
        if cell is not None and cell.lattice_vectors is not None:
            lattice = np.asarray(cell.lattice_vectors, dtype=float)
            if not _is_restricted(lattice):
                return _unrestricted_reason()
        header = stream_of(canonical).header
        has_molecule = _MOLECULE_KEY in header.custom_per_atom
        has_charges = frame.electronic.charges is not None
        if has_molecule and not has_charges:
            return (
                "lammps_data: the object carries a molecule-id but no charges; the only atom style "
                "that writes a molecule-id is 'full' (id molecule type q x y z), which requires a "
                "charge column — fabricating a zero charge (P3) or dropping the molecule-id (P1) "
                "are both refused"
            )
        clash = _mass_symbol_clash(frame)
        if clash is not None:
            symbol, m1, m2 = clash
            return (
                f"lammps_data: element {symbol!r} appears with more than one mass "
                f"({m1!r} and {m2!r} amu); a data file's Masses table is per atom type (one mass "
                "per symbol), so this distinction cannot be written without silently collapsing it"
            )
        return None

    def reparse_recovery(self, canonical: Any) -> dict[str, dict[str, object]] | None:
        """The recovery context the Validation Engine must apply to re-parse this exporter's own
        output (Part 5 §2; M48-S2, D181). A data file is the one write target whose output cannot
        self-describe: it states no unit system and identifies atoms by numeric type only, so a bare
        ``parse`` of the written bytes would hit the ``ambiguous_units`` refusal and never even
        re-read. This hands validation the *same* two choices the conversion already resolved and
        recorded as Assumptions — derived from the object just written, so the re-parse reproduces
        exactly the write:

        * ``ambiguous_units`` → the resolved style carried on ``custom_global['lammps_data:units']``
          (the write-side ``requires_units_style`` resolver placed it there);
        * ``missing_species`` → the ``type → symbol`` map from the same first-appearance numbering
          the write used (or the source's preserved numbering), as the parser's ``species_map``.

        Returns ``None`` only if no style rode the object — an inconsistent state the engine could
        not have written from, left for validation to surface honestly rather than papered over."""
        header = stream_of(canonical).header
        style_code = header.custom_global.get(_UNITS_KEY)
        if not isinstance(style_code, str):
            return None
        frame = canonical.frames[0]
        symbols = list(frame.atoms.symbols)
        _types, type_map, _preserved = _type_numbering(header, symbols)
        species = " ".join(
            f"{number}:{symbol}"
            for symbol, number in sorted(type_map.items(), key=lambda kv: kv[1])
        )
        return {
            "ambiguous_units": {"choice": style_code, "parameters": {}},
            "missing_species": {"choice": "species_map", "parameters": {"species": species}},
        }

    def capabilities(self) -> FormatCapabilities:
        none = FieldCapability(level=CapabilityLevel.NONE)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the numeric type column plus the per-type Masses table; the "
                        "type map (reported on write) records the symbol↔type assignment."
                    ),
                ),
                "atoms.positions": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Absolute Cartesian, unit-converted to the style's distance unit.",
                ),
                "atoms.masses": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the per-type Masses table (unit-converted); a data file needs "
                        "masses, so an object without them is refused via missing_masses, never "
                        "invented."
                    ),
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "LAMMPS restricted triclinic form only (edge rows (a,0,0),(xy,ly,0),"
                        "(xz,yz,lz)); any other cell is refused, never silently rotated."
                    ),
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Only fully periodic (p p p): a data file states no boundary line (LAMMPS "
                        "reads it from the input script's `boundary` command), so writing the box "
                        "is an implicit p-p-p statement the parser re-derives; any non-periodic "
                        "axis cannot be represented."
                    ),
                ),
                "cell.space_group": none,
                "dynamics.velocities": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the Velocities section when present (unit-converted); absent "
                        "stays absent."
                    ),
                ),
                "dynamics.forces": none,
                "dynamics.constraints": none,
                "electronic.total_energy": none,
                "electronic.stress": none,
                "electronic.charges": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the charge column of the charge/full atom styles when present "
                        "(unit-independent in the supported styles)."
                    ),
                ),
                "electronic.magnetic_moments": none,
                "simulation.*": none,
                "trajectory.timestep": none,
                "frame.time": none,
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "The title comment (lammps_data:comment), the resolved unit style "
                        "(lammps_data:units), and the verbatim topology payload "
                        "(lammps_data:topology) are written back; other keys are dropped."
                    ),
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Atom ids, molecule-ids (full style), numeric types, and image flags are "
                        "written back to their format-defined columns; a foreign-scoped key is "
                        "dropped."
                    ),
                ),
                "user_metadata.custom_per_frame": none,
            },
            # The writable metadata: the title/units/topology globals and the four per-atom carries.
            # Unlike the dump's open-ended compute columns, a data file's per-atom carries are a
            # fixed set (id/type/molecule-id/image-flags), so an exact key list — not a name
            # pattern — is the honest declaration.
            writable_custom_keys={
                "user_metadata.custom_global": [_COMMENT_KEY, _UNITS_KEY, _TOPOLOGY_KEY],
                "user_metadata.custom_per_atom": [
                    _ID_KEY,
                    _TYPE_KEY,
                    _MOLECULE_KEY,
                    IMAGE_FLAGS_CARRY_KEY,
                ],
            },
            max_frames=None,  # the unrepresentable hook refuses >1 frame with a clean message
            required_fields=[
                "atoms.symbols",
                "atoms.positions",
                "cell.lattice_vectors",
                "atoms.masses",
            ],
            allows_open_boundaries=False,  # a data file states a box; boundary is read from the run
            representable_constraint_kinds=[],
            native_coordinate_system="cartesian",
            # The named capability dimensions: a data file reads and writes image flags specifically
            # (holds_image_flags), and the write *requires* a declared unit style
            # (requires_units_style drives the write-side ambiguous_units refusal, no pre-flight
            # edit — the M47-S1 generalization).
            holds_image_flags=True,
            requires_units_style=True,
            lossy_notes=[
                "cell.pbc is written only implicitly: a data file states no boundary line (LAMMPS "
                "reads it from the input script's `boundary` command), so a fully-periodic box "
                "round-trips as p-p-p but a non-periodic axis cannot be recorded; and the box "
                "origin is written at zero (the parser drops the source origin — canonical "
                "positions are absolute)."
            ],
        )

    def _resolved_style(self, header: StreamHeader) -> UnitStyle:
        style_code = header.custom_global.get(_UNITS_KEY)
        style = unit_style(style_code) if isinstance(style_code, str) else None
        if style is None:
            raise ValueError(
                "lammps_data: no resolved unit style on the object "
                f"(custom_global[{_UNITS_KEY!r}] is {style_code!r}). A data file declares no unit "
                "system; convert with the ambiguous_units recovery preset (e.g. --recover "
                "ambiguous_units=metal) — never a guessed default"
            )
        return style


def _write_block(stream: BinaryIO, frame: Any, header: StreamHeader, style: UnitStyle) -> None:
    """Write the one configuration as a complete LAMMPS data file (Part 3 §3)."""
    distance = style.distance_to_angstrom
    symbols = list(frame.atoms.symbols)
    n_atoms = len(symbols)
    positions = np.asarray(frame.atoms.positions, dtype=float)

    topology = header.custom_global.get(_TOPOLOGY_KEY)
    header_counts, verbatim_masses, other_sections = _split_topology(topology)

    types_per_atom, _type_map, _preserved = _type_numbering(header, symbols)
    n_types = int(np.max(types_per_atom)) if n_atoms else 0

    lines: list[str] = []
    # Line 0 is the title comment: the carried title, or a blank line when the source had none
    # (writing a descriptive default would surface as a comment the source never carried — P3).
    title = header.custom_global.get(_COMMENT_KEY)
    lines.append(str(title) if isinstance(title, str) and title else "")
    lines.append("")

    lines.append(f"{n_atoms} atoms")
    if not _has_atom_types_line(header_counts):
        lines.append(f"{n_types} atom types")
    lines.extend(header_counts)
    lines.append("")

    lattice = _require_cell(frame)
    _require_restricted(lattice)
    lx, ly, lz, xy, xz, yz = edges_from_box(lattice)
    lines.append(f"{_fmt(0.0)} {_fmt(lx / distance)} xlo xhi")
    lines.append(f"{_fmt(0.0)} {_fmt(ly / distance)} ylo yhi")
    lines.append(f"{_fmt(0.0)} {_fmt(lz / distance)} zlo zhi")
    if max(abs(xy), abs(xz), abs(yz)) > 1e-12:
        lines.append(f"{_fmt(xy / distance)} {_fmt(xz / distance)} {_fmt(yz / distance)} xy xz yz")

    # Masses: the verbatim carried section (a declared-but-unused type S1 preserved), or regenerated
    # per type from atoms.masses (the ordinary case). Either way the section is present — a data
    # file requires masses, and the pre-flight refuses an object lacking them via missing_masses.
    lines.append("")
    if verbatim_masses is not None:
        lines.append(_section_keyword("Masses", verbatim_masses.get("comment")))
        lines.append("")
        lines.extend(str(row) for row in verbatim_masses.get("rows", []))
    else:
        lines.append("Masses")
        lines.append("")
        lines.extend(_regenerated_masses(frame, symbols, types_per_atom, style))

    # Atoms: the style is inferred from what the object carries (molecule-id → full, else charges →
    # charge, else atomic); the column layout is the exact inverse of the parser's.
    style_name, layout = _write_style(header, frame)
    lines.append("")
    lines.append(f"Atoms # {style_name}")
    lines.append("")
    lines.extend(_atom_rows(header, frame, symbols, types_per_atom, positions, layout, distance))

    if frame.dynamics.velocities is not None:
        lines.append("")
        lines.append("Velocities")
        lines.append("")
        lines.extend(_velocity_rows(header, frame, n_atoms, style))

    # Every other carried topology section (Bonds/Angles/… , * Coeffs, unrecognized), verbatim and
    # in file order — the byte-faithful data→data topology write-back.
    for section in other_sections:
        lines.append("")
        lines.append(_section_keyword(str(section.get("section", "")), section.get("comment")))
        lines.append("")
        lines.extend(str(row) for row in section.get("rows", []))

    stream.write(("\n".join(lines) + "\n").encode("utf-8"))


def _split_topology(
    topology: Any,
) -> tuple[list[str], dict[str, Any] | None, list[dict[str, Any]]]:
    """Split the carried topology payload into (header count lines, the verbatim Masses section if
    any, every other section). The Masses section is separated so it can be written in its
    conventional position (after the box); it is present only for a declared-but-unused atom type
    (M48-S1)."""
    if not isinstance(topology, dict):
        return [], None, []
    header_counts = [str(line) for line in topology.get("header_counts", [])]
    verbatim_masses: dict[str, Any] | None = None
    other: list[dict[str, Any]] = []
    for section in topology.get("sections", []):
        if not isinstance(section, dict):
            continue
        if section.get("section") == "Masses":
            verbatim_masses = section
        else:
            other.append(section)
    return header_counts, verbatim_masses, other


def _type_numbering(
    header: StreamHeader, symbols: list[str]
) -> tuple[np.ndarray, dict[str, int], bool]:
    """The numeric type per atom, the reported symbol→type map, and whether source numbering was
    preserved.

    When the object carries a verbatim ``Masses`` section (a data source with a declared-but-unused
    type), the source's own ``lammps_data:type`` numbering is preserved so that carried section
    stays consistent with the Atoms rows. Otherwise types are assigned deterministically by first
    appearance (Si=1, O=2, …), exactly as the dump exporter does, so a round-trip is stable."""
    topology = header.custom_global.get(_TOPOLOGY_KEY)
    _counts, verbatim_masses, _other = _split_topology(topology)
    carried = header.custom_per_atom.get(_TYPE_KEY)
    if verbatim_masses is not None and carried is not None:
        types = np.asarray(carried).astype(np.int64)
        type_map: dict[str, int] = {}
        for symbol, t in zip(symbols, types, strict=True):
            type_map.setdefault(symbol, int(t))
        return types, type_map, True
    type_map = {}
    for symbol in symbols:
        if symbol not in type_map:
            type_map[symbol] = len(type_map) + 1
    types = np.asarray([type_map[s] for s in symbols], dtype=np.int64)
    return types, type_map, False


def _write_style(header: StreamHeader, frame: Any) -> tuple[str, tuple[str, ...]]:
    """The atom style to declare and its column layout. A carried molecule-id needs ``full``; else a
    charge needs ``charge``; else ``atomic``. The molecule-without-charge and other value-level
    obstructions are refused upstream by ``unrepresentable``, so this only picks among the writable
    styles."""
    if _MOLECULE_KEY in header.custom_per_atom:
        return "full", _STYLE_LAYOUTS["full"]
    if frame.electronic.charges is not None:
        return "charge", _STYLE_LAYOUTS["charge"]
    return "atomic", _STYLE_LAYOUTS["atomic"]


def _atom_rows(
    header: StreamHeader,
    frame: Any,
    symbols: list[str],
    types_per_atom: np.ndarray,
    positions: np.ndarray,
    layout: tuple[str, ...],
    distance: float,
) -> list[str]:
    """The ``Atoms`` data rows in the declared style's column order, with a trailing ``ix iy iz``
    triple when the object carries image flags."""
    n_atoms = len(symbols)
    ids = _carried_ids(header, n_atoms)
    molecules = header.custom_per_atom.get(_MOLECULE_KEY)
    molecules_array = None if molecules is None else np.asarray(molecules)
    charges = frame.electronic.charges
    charges_array = None if charges is None else np.asarray(charges, dtype=float)
    coords = positions / distance
    image_flags = _image_flags(header, n_atoms)

    rows: list[str] = []
    for i in range(n_atoms):
        fields: list[str] = []
        for name in layout:
            if name == "id":
                fields.append(_fmt_id(ids[i]))
            elif name == "molecule":
                fields.append(_fmt_id(molecules_array[i]))  # type: ignore[index]
            elif name == "type":
                fields.append(str(int(types_per_atom[i])))
            elif name == "q":
                fields.append(_fmt(charges_array[i]))  # type: ignore[index]
            elif name == "x":
                fields.append(_fmt(coords[i, 0]))
            elif name == "y":
                fields.append(_fmt(coords[i, 1]))
            else:  # "z"
                fields.append(_fmt(coords[i, 2]))
        if image_flags is not None:
            fields.extend(str(int(v)) for v in image_flags[i])
        rows.append(" ".join(fields))
    return rows


def _velocity_rows(header: StreamHeader, frame: Any, n_atoms: int, style: UnitStyle) -> list[str]:
    """The ``Velocities`` rows (``id vx vy vz``), unit-converted to the style's basis and using the
    same atom ids as the Atoms section (carried, or a 1..N numbering)."""
    ids = _carried_ids(header, n_atoms)
    velocities = np.asarray(frame.dynamics.velocities, dtype=float)
    velocities = velocities / style.velocity_to_angstrom_per_femtosecond
    rows: list[str] = []
    for i in range(n_atoms):
        rows.append(
            f"{_fmt_id(ids[i])} {_fmt(velocities[i, 0])} {_fmt(velocities[i, 1])} "
            f"{_fmt(velocities[i, 2])}"
        )
    return rows


def _regenerated_masses(
    frame: Any, symbols: list[str], types_per_atom: np.ndarray, style: UnitStyle
) -> list[str]:
    """A regenerated ``Masses`` table (``type mass``), one row per type in ascending type order, the
    mass taken from ``atoms.masses`` (divided back to the style's mass unit). The same-symbol clash
    is refused upstream by ``unrepresentable``, so one mass per type is well-defined here."""
    masses = frame.atoms.masses
    if masses is None:
        # Defensive backstop: atoms.masses is a write required_field, so the pre-flight refuses an
        # object without them via missing_masses before this exporter is reached.
        raise ValueError(
            "lammps_data requires atoms.masses; supply it via the missing_masses recovery before "
            "export (Part 4 §3)"
        )
    masses_array = np.asarray(masses, dtype=float)
    mass_by_type: dict[int, float] = {}
    for i in range(len(symbols)):
        t = int(types_per_atom[i])
        if t not in mass_by_type:
            mass_by_type[t] = masses_array[i] / style.mass_to_amu
    return [f"{t} {_fmt(mass_by_type[t])}" for t in sorted(mass_by_type)]


def _carried_ids(header: StreamHeader, n_atoms: int) -> np.ndarray:
    """The carried atom ids, or a 1..N numbering when the object carries none (never a synthesized
    numbering presented as the source's — a data file needs ids, so a generated 1..N is the honest
    default, stated as generated by the absence of the carry)."""
    carried = header.custom_per_atom.get(_ID_KEY)
    if carried is None:
        return np.arange(1, n_atoms + 1, dtype=np.int64)
    ids = np.asarray(carried)
    if ids.shape[0] != n_atoms:
        raise ValueError(
            f"lammps_data: the carried id column has {ids.shape[0]} entries but the object has "
            f"{n_atoms} atoms"
        )
    return ids


def _image_flags(header: StreamHeader, n_atoms: int) -> np.ndarray | None:
    """The carried per-atom image flags as an integer ``(N, 3)`` array, or ``None`` when absent
    (never synthesized — a zero triple would assert no atom has crossed a boundary, P3)."""
    carried = header.custom_per_atom.get(IMAGE_FLAGS_CARRY_KEY)
    if carried is None:
        return None
    flags = np.asarray(carried)
    if flags.shape != (n_atoms, 3):
        raise ValueError(
            f"lammps_data: image flags must have shape ({n_atoms}, 3), got {flags.shape}"
        )
    if not np.all(np.isfinite(flags)) or not np.all(flags == np.floor(flags)):
        raise ValueError("lammps_data: image flags must be finite integer triplets")
    return flags.astype(np.int64)


def _mass_symbol_clash(frame: Any) -> tuple[str, float, float] | None:
    """The first element symbol that appears with two different masses, or ``None``. A data file's
    Masses table is per type (one mass per symbol), so a clash is unrepresentable (checked before
    export by ``unrepresentable``)."""
    masses = frame.atoms.masses
    if masses is None:
        return None
    masses_array = np.asarray(masses, dtype=float)
    seen: dict[str, float] = {}
    for symbol, mass in zip(frame.atoms.symbols, masses_array, strict=True):
        if symbol in seen:
            if not np.isclose(seen[symbol], mass):
                return str(symbol), float(seen[symbol]), float(mass)
        else:
            seen[symbol] = float(mass)
    return None


def _has_atom_types_line(header_counts: list[str]) -> bool:
    """Whether the carried header count lines already state an ``atom types`` line (the
    declared-but-unused-type case S1 folds into the topology carry) — so the exporter does not emit
    a second one."""
    return any(line.split()[-2:] == ["atom", "types"] for line in header_counts if line.split())


def _section_keyword(name: str, comment: Any) -> str:
    """A body-section keyword line, restoring the trailing ``# comment`` when the carry held one."""
    if isinstance(comment, str) and comment:
        return f"{name}  # {comment}"
    return name


def _require_cell(frame: Any) -> np.ndarray:
    if frame.cell is None or frame.cell.lattice_vectors is None:
        raise ValueError(
            "lammps_data requires cell.lattice_vectors and the frame has none; supply it via the "
            "missing_lattice recovery before export (Part 4 §3)"
        )
    return np.asarray(frame.cell.lattice_vectors, dtype=float)


def _is_restricted(lattice: np.ndarray) -> bool:
    """Whether ``lattice`` is in LAMMPS's restricted triclinic form (upper-triangle zeros: edge
    **a** along x, **b** in the xy-plane) — the one value-level geometry a data file can state."""
    return bool(
        np.allclose(lattice[0, 1], 0.0)
        and np.allclose(lattice[0, 2], 0.0)
        and np.allclose(lattice[1, 2], 0.0)
    )


def _unrestricted_reason() -> str:
    """The plain-language reason a non-restricted cell cannot be written — shared by the
    engine-consulted ``unrepresentable`` refusal and the defensive raise in ``_require_restricted``,
    so the refused report and the backstop crash say the same thing."""
    return (
        "lammps_data: the lattice is not LAMMPS's restricted triclinic form "
        "((a,0,0),(xy,ly,0),(xz,yz,lz)); a data file cannot state it — a rotation would silently "
        "change the configuration's frame of reference"
    )


def _require_restricted(lattice: np.ndarray) -> None:
    """Defensive backstop: the engine consults ``unrepresentable`` and refuses a non-restricted cell
    before export, so this only fires if that guard is ever bypassed."""
    if not _is_restricted(lattice):
        raise ValueError(_unrestricted_reason())


def _fmt(x: float) -> str:
    return repr(float(x))


def _fmt_id(value: Any) -> str:
    """Format a carried atom id / molecule-id. LAMMPS ids are integers, but the parser carries them
    as (possibly float) arrays, so emit an integer-valued id without the decimal point; fall back to
    the float repr only for a pathological non-integer carry (never silently truncating it)."""
    f = float(value)
    if np.isfinite(f) and f == np.floor(f):
        return str(int(f))
    return repr(f)


def make_lammps_data_exporter() -> LammpsDataExporter:
    return LammpsDataExporter()
