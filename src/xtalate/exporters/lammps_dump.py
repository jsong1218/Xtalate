"""LAMMPS dump exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v1.3 M47-S1, D177).

The write side of the deployment format, mirroring ``parsers.lammps_dump``: it turns a
Canonical Object back into an ``ITEM:``-block dump trajectory. Every mapping is the exact
inverse of the parser's (D177):

* **Units run through the shared core in the inverse direction.** The canonical model is
  fixed in Å/fs/eV, and a LAMMPS file only means anything when its unit style is declared —
  so the exporter writes the ``ITEM: UNITS <style>`` header (the resolved
  ``ambiguous_units`` choice, carried on the object as ``custom_global['lammps_dump:units']``
  exactly as the write-side recovery resolver placed it) and converts positions, box bounds,
  and velocities from the canonical basis to that style's units — the same hand-verified
  factors M46's ``sdk.lammps.units`` tables hold, applied the other way. Without a resolved
  style there is **no** write: the pre-flight diff refuses with ``ambiguous_units`` before
  this exporter is ever reached, so a dump that silently carries a guessed unit basis cannot
  come out of Xtalate (**P4**; the write-side twin of the parse-side refusal).
* **An element column and a generated type map.** LAMMPS identifies atoms by numeric
  ``type``; the canonical object carries element symbols. The exporter writes the ``element``
  column *and* assigns deterministic numeric types by first appearance (Si=1, O=2, … in
  first-seen order, so a round-trip is stable), reporting the mapping as an export warning —
  the audit line in the Conversion Report (never an unrecorded renumbering).
* **Velocities only when present (P3).** ``vx vy vz`` columns are written only when the
  frame carries ``dynamics.velocities`` — an absent velocity block stays absent, never
  zero-filled (a zero block would assert a rest state the source never claimed).
* **Triclinic boxes written back through the M46 core in reverse.** The canonical lattice
  (restricted triclinic form, the form a dump can state) is expanded to the ``ITEM: BOX
  BOUNDS xy xz yz`` bounding form with the exact inverse of M46's ``box_from_bounds``
  (D174). A lattice outside the restricted form is **refused**, never silently rotated
  (declared as the PARTIAL cell condition). Image flags are *not* written in S1 (their
  round-trip symmetry is M47-S2).

**Streaming-first**, mirroring the parser and ``xdatcar``: ``export`` is defined as
``export_stream`` over the materialized object's frames, so the whole-file and streamed
writings are one code path and cannot diverge. Dump-as-*target* still routes through the
materialized ``convert`` — the write needs the ``ambiguous_units`` recovery resolved before
a byte is written, a static fact the streaming path refuses by contract (reconciliation 3,
D177); this exporter's streaming shape is for one-code-path honesty and SDK-level use.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, BinaryIO

import numpy as np

from xtalate.schema.presence import compute_field_presence
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
from xtalate.sdk.lammps import unit_style
from xtalate.sdk.lammps.units import UnitStyle

FORMAT_ID = "lammps_dump"

# The custom_global key the resolved unit style rides under — the write-side recovery
# resolver places it there and the parser carries a declared/recovered style back under the
# same spelling, so the re-parse reproduces what the exporter wrote (Part 5 §2).
_UNITS_KEY = f"{FORMAT_ID}:units"
# The per-frame custom key the dump's step number rides under (parser carry, _STEP_KEY).
_STEP_KEY = f"{FORMAT_ID}:timestep"
# The per-atom custom key an `id` column rides under (parser carry, _ID_KEY).
_ID_KEY = f"{FORMAT_ID}:id"
#: The per-atom custom keys this exporter writes back as dump columns (M47-S1/S2): generic
#: ``lammps_dump:<name>`` columns round-trip verbatim, while the reserved ``id``/``type``
#: carries are represented by the writer's canonical ``id``/generated ``type`` columns and the
#: image-flags carry is expanded into its specific ``ix iy iz`` family. The pattern is declared
#: to pre-flight so the write plan and bytes cannot drift; the exporter keeps the reserved carries
#: out of the generic-column loop and handles them in their format-defined positions.
_WRITABLE_PER_ATOM = re.compile(rf"{FORMAT_ID}:(?!(?:id|type)$)[^:]*")

#: Audit-line code for the generated type map (surfaced in the Conversion Report via
#: ``export_warnings`` — the exporter-owned report channel).
_TYPES_ASSIGNED = "LAMMPSDUMP_TYPES_ASSIGNED"


class LammpsDumpExporter(ExporterPlugin):
    """LAMMPS dump writer (Part 3 §3)."""

    format_id = FORMAT_ID
    format_name = "LAMMPS dump"
    version = "0.1.0"

    def export(self, canonical: Any, stream: BinaryIO) -> None:
        """Whole-file write, defined as the streamed write over the object's own frames — so a
        streamed and a materialized export are the same code, never two paths (D56)."""
        frame_stream = stream_of(canonical)
        self.export_stream(frame_stream.header, frame_stream.frames(), stream)

    def supports_streaming(self) -> bool:
        return True

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        style_code = header.custom_global.get(_UNITS_KEY)
        style = unit_style(style_code) if isinstance(style_code, str) else None
        coordinate_kind = _coordinate_kind(header)
        if style is None:
            raise ValueError(
                "lammps_dump: no resolved unit style on the object "
                f"(custom_global[{_UNITS_KEY!r}] is {style_code!r}). A dump only means "
                "anything with a declared ITEM: UNITS header; convert with the "
                "ambiguous_units recovery preset (e.g. --recover ambiguous_units=metal) — "
                "never a guessed default"
            )

        # The type map is assigned once, on the first frame, in first-appearance order — a
        # deterministic 1..K numbering that makes a round-trip stable — and every later frame
        # must be expressible under it (constant atom identity, the parser's own rule).
        type_map: dict[str, int] = {}
        written_units = False
        for i, sf in enumerate(frames):
            frame = sf.frame
            _extend_type_map(type_map, frame.atoms.symbols, i)
            if not written_units:
                # LAMMPS declares the unit style in the first snapshot's preamble block
                # (dump.cpp write_header), as a two-line ITEM.
                stream.write(f"ITEM: UNITS\n{style.code}\n".encode())
                written_units = True
            _write_snapshot(
                stream,
                frame,
                i,
                sf.per_frame_custom,
                header,
                style,
                type_map,
                coordinate_kind,
            )

        if not written_units:
            raise ValueError("lammps_dump: the object being exported has no frames")

    def export_warnings(self, canonical: Any) -> list[ExporterWarning]:
        """The one transformation this exporter applies that must be audited: it *renumbers*
        atoms into LAMMPS numeric types, so the mapping is stated in the Conversion Report as
        an audit line (deterministic first-appearance order, never a silent renumbering)."""
        type_map: dict[str, int] = {}
        if canonical.frames:
            _extend_type_map(type_map, canonical.frames[0].atoms.symbols, 0)
        mapping = ", ".join(f"type {number} → {symbol}" for symbol, number in type_map.items())
        return [
            ExporterWarning(
                code=_TYPES_ASSIGNED,
                message=(
                    "Assigned LAMMPS atom types by first appearance: "
                    f"{mapping or 'none (the object has no atoms)'}."
                ),
            )
        ]

    def unrepresentable(self, canonical: Any) -> str | None:
        """Why the dump format cannot express ``canonical``'s *values*, or ``None`` when it can
        (Part 4 §1; D179). A returned string produces a clean ``UNREPRESENTABLE_VALUE`` refusal, not
        an export-time crash (P1). Two value-level facts the field-granular Capability Matrix cannot
        see are checked here, before export:

        1. **A general-triclinic cell.** A dump can state only the *restricted* triclinic form; any
           other cell would need a rotation to write, silently changing the trajectory's frame of
           reference (D43). A frame with **no** lattice is not this method's concern — that is a
           required-field gap the pre-flight / ``missing_lattice`` recovery handles — so only frames
           that carry a lattice are checked.
        2. **Mixed-presence velocities.** A dump requires a *constant* per-atom column layout across
           every snapshot, so it cannot carry ``vx vy vz`` on only some frames. When the presence
           model reports ``dynamics.velocities`` as ``mixed`` (present on some frames, absent on
           others — a legitimate canonical state), writing it would demand either per-frame-varying
           columns (output the parser rejects) or a fabricated rest state for the gap frames
           (forbidden, P3/P1). Neither is allowed, so the conversion is refused rather than silently
           mangled. A uniformly-present or uniformly-absent velocity field is representable and
           passes."""
        for index, frame in enumerate(canonical.frames):
            cell = frame.cell
            if cell is None or cell.lattice_vectors is None:
                continue
            lattice = np.asarray(cell.lattice_vectors, dtype=float)
            if not _is_restricted(lattice):
                return _unrestricted_reason(index)
        if compute_field_presence(canonical).status_of("dynamics.velocities") == "mixed":
            return _mixed_velocities_reason(canonical.frames)
        return None

    def capabilities(self) -> FormatCapabilities:
        none = FieldCapability(level=CapabilityLevel.NONE)
        style_notes = (
            "Only the declared unit style (lammps_dump:units) — written as the "
            "ITEM: UNITS header; other custom_global keys are dropped."
        )
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as an element column; the numeric type column carries the "
                        "deterministic type map (reported on write)."
                    ),
                ),
                "atoms.positions": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Unit-converted to the style's distance unit on write.",
                ),
                "atoms.masses": none,
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "LAMMPS restricted triclinic form only "
                        "(edge rows (a,0,0),(xy,ly,0),(xz,yz,lz)); any other cell is "
                        "refused, never silently rotated."
                    ),
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the BOX BOUNDS boundary flags "
                        "(p per periodic axis, f otherwise)."
                    ),
                ),
                "cell.space_group": none,
                "dynamics.velocities": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as vx vy vz columns when present (unit-converted); "
                        "absent stays absent."
                    ),
                ),
                "dynamics.forces": none,
                "dynamics.constraints": none,
                "electronic.total_energy": none,
                "electronic.stress": none,
                "electronic.charges": none,
                "electronic.magnetic_moments": none,
                "simulation.*": none,
                # The dump writes step numbers per snapshot, never a dt in fs, so the canonical
                # timestep (which needs a dt) cannot be expressed; the step numbers ride the
                # custom_per_frame carry instead.
                "trajectory.timestep": none,
                "frame.time": none,
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL, notes=style_notes
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Generic carried columns (lammps_dump:<name>) are written back verbatim; "
                        "id/type carries are represented by the id/generated-type columns, and "
                        "image flags are written as ix/iy/iz when carried; a foreign-scoped key "
                        "is dropped."
                    ),
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "The per-snapshot step number rides ITEM: TIMESTEP; "
                        "ITEM: TIME carries are not written."
                    ),
                ),
            },
            # Only the resolved unit style (custom_global) and the per-snapshot step number
            # (custom_per_frame) are writable metadata; a foreign key has no home in a dump
            # and is routed `removed` by the pre-flight per-key rule. Per-atom custom columns
            # are open-ended (any compute/fix output), so that writable set is a name pattern
            # (D69) — minus the S1-excluded image-flag carry (above).
            writable_custom_keys={
                "user_metadata.custom_global": [_UNITS_KEY],
                "user_metadata.custom_per_frame": [_STEP_KEY],
            },
            writable_custom_key_pattern={
                "user_metadata.custom_per_atom": _WRITABLE_PER_ATOM.pattern
            },
            max_frames=None,  # the point of the format: an unbounded snapshot count
            required_fields=["atoms.symbols", "atoms.positions", "cell.lattice_vectors"],
            allows_open_boundaries=True,  # the f boundary flag expresses a non-periodic axis
            representable_constraint_kinds=[],
            native_coordinate_system="cartesian",
            # The named capability dimensions (M46-S3 / M47-S2): the dump reads and writes
            # image flags specifically, while the write *requires* a declared unit style
            # (requires_units_style drives the write-side ambiguous_units refusal).
            holds_image_flags=True,
            requires_units_style=True,
            lossy_notes=[
                "Per-snapshot ITEM: TIME / simulation-time carries are not written (a dump "
                "time axis needs the run's unit convention, which the write style cannot "
                "verify); step numbers ride ITEM: TIMESTEP (carried or renumbered from 0)."
            ],
        )


def _coordinate_kind(header: StreamHeader) -> str:
    """Recover the source coordinate family from parser provenance for a write round-trip.

    The LAMMPS parser records this format-defined fact in ``provenance.parse_notes``. A
    programmatically constructed canonical object has no such note, so the safe default is the
    ordinary wrapped Cartesian family (x/y/z), which is also the historical S1 output.
    """
    for note in header.provenance.parse_notes:
        if "scaled (xs/ys/zs)" in note:
            return "scaled"
        if "unwrapped Cartesian (xu/yu/zu)" in note:
            return "unwrapped"
        if "wrapped Cartesian (x/y/z)" in note:
            return "cartesian"
    return "cartesian"


def _extend_type_map(type_map: dict[str, int], symbols: list[str], index: int) -> None:
    """Assign numeric LAMMPS atom types by *first appearance* across the trajectory (Si=1,
    O=2, …), raising if a later frame introduces a species the map has not seen — the writer
    cannot express a type whose identity it has not recorded (the parser's own
    constant-identity rule). Deterministic so a round-trip is stable."""
    for symbol in symbols:
        if symbol not in type_map:
            type_map[symbol] = len(type_map) + 1
    # A frame must be fully expressible under the map built so far. (Symbols are per-atom
    # identities; a trajectory that changes species mid-way cannot be one dump.)
    missing = [s for s in symbols if s not in type_map]
    if missing:
        raise ValueError(
            "lammps_dump: frame "
            f"{index} introduces species {sorted(set(missing))} not seen in the trajectory's "
            "first frame; a dump has one type map for the whole run"
        )


def _require_cell(frame: Any, index: int) -> np.ndarray:
    if frame.cell is None or frame.cell.lattice_vectors is None:
        raise ValueError(
            f"lammps_dump requires cell.lattice_vectors and frame {index} has none; supply "
            "it via the missing_lattice recovery before export (Part 4 §3)"
        )
    return np.asarray(frame.cell.lattice_vectors, dtype=float)


def _write_snapshot(
    stream: BinaryIO,
    frame: Any,
    index: int,
    per_frame_custom: dict[str, Any],
    header: StreamHeader,
    style: UnitStyle,
    type_map: dict[str, int],
    coordinate_kind: str,
) -> None:
    """One ``ITEM:``-block snapshot. Shared by whole-file and streamed writes (one code path)."""
    distance = style.distance_to_angstrom

    lattice = _require_cell(frame, index)
    _require_restricted(lattice, index)
    lx, ly, lz = lattice[0, 0], lattice[1, 1], lattice[2, 2]
    xy, xz, yz = lattice[1, 0], lattice[2, 0], lattice[2, 1]
    tilted = max(abs(xy), abs(xz), abs(yz)) > 1e-12
    pbc = frame.cell.pbc if frame.cell is not None else (True, True, True)
    # The boundary flags are per-axis tokens (the parser reads each token's first character
    # for the periodic flag): "p p p" for a fully periodic box, "f f f" for an open one.
    flags = " ".join("p" if bool(b) else "f" for b in pbc)

    # The step number: the carried per-snapshot step when the source had one, else renumber
    # from 0 (a canonical object has no step axis — the honest default, never a fake dt). A
    # dump's TIMESTEP line is an integer, so a carried float is emitted at integer precision

    # (parse-side steps are integral by construction).
    step = per_frame_custom.get(_STEP_KEY)
    if isinstance(step, bool) or not isinstance(step, (int, float)):
        step_value = index
    else:
        step_value = int(step) if float(step).is_integer() else index

    out = [
        "ITEM: TIMESTEP",
        str(step_value),
        "ITEM: NUMBER OF ATOMS",
        str(len(frame.atoms.symbols)),
    ]
    if tilted:
        xlo_b = min(0.0, xy, xz, xy + xz)
        xhi_b = lx + max(0.0, xy, xz, xy + xz)
        ylo_b = min(0.0, yz)
        yhi_b = ly + max(0.0, yz)
        out.append(f"ITEM: BOX BOUNDS xy xz yz {flags}")
        out.append(f"{_fmt(xlo_b / distance)} {_fmt(xhi_b / distance)} {_fmt(xy / distance)}")
        out.append(f"{_fmt(ylo_b / distance)} {_fmt(yhi_b / distance)} {_fmt(xz / distance)}")
        out.append(f"{_fmt(0.0)} {_fmt(lz / distance)} {_fmt(yz / distance)}")
    else:
        out.append(f"ITEM: BOX BOUNDS {flags}")
        out.append(f"{_fmt(0.0)} {_fmt(lx / distance)}")
        out.append(f"{_fmt(0.0)} {_fmt(ly / distance)}")
        out.append(f"{_fmt(0.0)} {_fmt(lz / distance)}")

    # The ATOMS column set: id (carried) · element · generated type · the source coordinate
    # convention · optional velocities · image flags · carried custom columns. Reserved carries
    # are handled explicitly below so they cannot appear twice in the header.
    symbols = list(frame.atoms.symbols)
    positions = np.asarray(frame.atoms.positions, dtype=float)
    if coordinate_kind == "scaled":
        # The writer emits a zero-origin box, so express canonical Cartesian positions as
        # fractional coordinates in the restricted lattice. This is the inverse of the parser's
        # scaled_to_cartesian mapping and preserves xs/ys/zs as a convention, not merely as a
        # spelling change.
        fractional = positions @ np.linalg.inv(lattice)
        coordinate_values = fractional
        coordinate_names = ("xs", "ys", "zs")
    else:
        # x/y/z and xu/yu/zu are both Cartesian in the writer's zero-origin box; only the
        # coordinate family distinguishes wrapped from unwrapped semantics. The canonical object
        # deliberately retains the source values exactly as read (the parser never auto-unwraps).
        coordinate_values = positions / distance
        coordinate_names = ("x", "y", "z") if coordinate_kind == "cartesian" else ("xu", "yu", "zu")
    custom_values = [
        (key[len(FORMAT_ID) + 1 :], np.asarray(values, dtype=float))
        for key, values in header.custom_per_atom.items()
        if _WRITABLE_PER_ATOM.fullmatch(key)
        and key not in {_ID_KEY, f"{FORMAT_ID}:type", IMAGE_FLAGS_CARRY_KEY}
    ]
    image_flags = header.custom_per_atom.get(IMAGE_FLAGS_CARRY_KEY)
    image_flags_array = None if image_flags is None else np.asarray(image_flags)
    if image_flags_array is not None:
        if image_flags_array.shape != (len(symbols), 3):
            raise ValueError(
                "lammps_dump: image flags must have shape "
                f"({len(symbols)}, 3), got {image_flags_array.shape}"
            )
        if not np.all(np.isfinite(image_flags_array)) or not np.all(
            image_flags_array == np.floor(image_flags_array)
        ):
            raise ValueError("lammps_dump: image flags must be finite integer triplets")
        # Image flags are integer bookkeeping by definition; cast after the
        # finite/integer-valued guard so they render as `0` not `0.0`.
        image_flags_array = image_flags_array.astype(np.int64)
    # The id column is written **only when the object carries it** (round-tripped identity);
    # a source without one gets no id column — never a synthesized numbering presented as the
    # source's (P3). The column header and the rows must agree by construction, so the same
    # flag gates both.
    has_velocities = frame.dynamics.velocities is not None
    has_ids = _ID_KEY in header.custom_per_atom
    columns: list[str] = []
    if has_ids:
        columns.append("id")
    columns += ["element", "type", *coordinate_names]
    if has_velocities:
        columns += ["vx", "vy", "vz"]
    if image_flags_array is not None:
        columns += ["ix", "iy", "iz"]
    columns += [name for name, _ in custom_values]
    out.append("ITEM: ATOMS " + " ".join(columns))

    n_atoms = len(symbols)
    for atom_index, symbol in enumerate(symbols):
        row = []
        if has_ids:
            _values = header.custom_per_atom[_ID_KEY]
            if atom_index >= len(_values):
                raise ValueError(
                    "lammps_dump: the carried id column is shorter than the atom count ("
                    f"{len(_values)} < {n_atoms})"
                )
            row.append(_fmt_number(float(_values[atom_index])))
        row.append(symbol)
        row.append(str(type_map[symbol]))
        row.append(_fmt(coordinate_values[atom_index, 0]))
        row.append(_fmt(coordinate_values[atom_index, 1]))
        row.append(_fmt(coordinate_values[atom_index, 2]))
        if has_velocities:
            velocity = (
                np.asarray(frame.dynamics.velocities, dtype=float)
                / style.velocity_to_angstrom_per_femtosecond
            )
            row.append(_fmt(velocity[atom_index, 0]))
            row.append(_fmt(velocity[atom_index, 1]))
            row.append(_fmt(velocity[atom_index, 2]))
        if image_flags_array is not None:
            row.extend(_fmt_number(value) for value in image_flags_array[atom_index])
        for _, values in custom_values:
            if atom_index >= len(values):
                raise ValueError(
                    "lammps_dump: a carried custom column is shorter than the atom count ("
                    f"{len(values)} < {n_atoms})"
                )
            row.append(_fmt_number(values[atom_index]))
        out.append(" ".join(row))
    stream.write(("\n".join(out) + "\n").encode("utf-8"))


def _is_restricted(lattice: np.ndarray) -> bool:
    """Whether ``lattice`` is in LAMMPS's *restricted* triclinic form (upper-triangle zeros: edge
    **a** along x, **b** in the xy-plane). This is the one value-level geometry a dump can state;
    any other cell would need a rotation to write, which would silently change the trajectory's
    frame of reference — an unrequested transform Xtalate refuses rather than performs (D43)."""
    return bool(
        np.allclose(lattice[0, 1], 0.0)
        and np.allclose(lattice[0, 2], 0.0)
        and np.allclose(lattice[1, 2], 0.0)
    )


def _unrestricted_reason(index: int) -> str:
    """The plain-language reason a non-restricted cell cannot be written — shared verbatim by the
    engine-consulted :meth:`LammpsDumpExporter.unrepresentable` refusal and the defensive raise in
    ``_require_restricted``, so the refused report and the backstop crash say the same thing."""
    return (
        f"lammps_dump: frame {index}'s lattice is not LAMMPS's restricted triclinic form "
        "((a,0,0),(xy,ly,0),(xz,yz,lz)); the format cannot state it — a rotation would silently "
        "change the trajectory's frame of reference"
    )


def _require_restricted(lattice: np.ndarray, index: int) -> None:
    """Defensive backstop for the write path: the engine consults ``unrepresentable`` and refuses
    a non-restricted cell *before* export, so this only fires if that guard is ever bypassed."""
    if not _is_restricted(lattice):
        raise ValueError(_unrestricted_reason(index))


def _mixed_velocities_reason(frames: list[Any]) -> str:
    """The plain-language reason a *mixed*-presence velocity field cannot be written: a dump's
    per-atom column layout must be identical across every snapshot, so ``vx vy vz`` cannot appear on
    only part of the trajectory. Names the first frame that breaks the pattern for a concrete
    pointer. Consulted only after :func:`compute_field_presence` has classified the field ``mixed``,
    so both a present and an absent frame are guaranteed to exist."""
    present = [f.index for f in frames if f.dynamics.velocities is not None]
    absent = [f.index for f in frames if f.dynamics.velocities is None]
    return (
        "lammps_dump: velocities are present on some frames but absent on others "
        f"(present on {len(present)} of {len(frames)} frames; first frame without them is "
        f"{absent[0]}). A dump requires a constant per-atom column layout across every "
        "snapshot, so it cannot carry velocities on only part of the trajectory — and "
        "fabricating a rest state for the gap frames would assert a stillness the source "
        "never recorded (P3)"
    )


def _fmt(x: float) -> str:
    return repr(float(x))


def _fmt_number(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return repr(float(value))


def make_lammps_dump_exporter() -> LammpsDumpExporter:
    return LammpsDumpExporter()
