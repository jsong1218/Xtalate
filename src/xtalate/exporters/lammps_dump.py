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

from xtalate.sdk import (
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
#: The per-atom custom keys this exporter writes back as dump columns (M47-S1): the generic
#: carried columns (``lammps_dump:<name>`` — compute/fix outputs, id) round-trip verbatim,
#: declared to the pre-flight as the writable pattern so the write plan and the bytes cannot
#: drift. The one exclusion is the **image-flag carry** (M46-S3): S1 does not yet write
#: ``ix iy iz`` back (that is M47-S2), so the key deliberately fails this pattern and is
#: routed ``removed`` — with the M46 pre-flight predicting
#: ``LAMMPSDUMP_UNWRAPPING_LOST_ON_EXPORT`` against the S1 write capability
#: (``holds_image_flags=False``), an honest predicted loss, never a silent one. S2 flips the
#: capability *and* this pattern together with the flag-writing behavior.
_WRITABLE_PER_ATOM = re.compile(rf"{FORMAT_ID}:(?!image_flags)[^:]*")

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
            _write_snapshot(stream, frame, i, sf.per_frame_custom, header, style, type_map)

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
                        "the image-flag carry is not written in S1 (predicted loss), and a "
                        "foreign-scoped key is dropped."
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
            # The named capability dimensions (M46-S3 / M47-S1): the dump reads *and* carries
            # image flags, but S1 does not yet write them back (holds_image_flags stays False
            # until S2 lands the flag-writing behavior with it — the S1→S2 resting-state
            # contract), while the write *requires* a declared unit style (requires_units_style
            # drives the write-side ambiguous_units refusal).
            holds_image_flags=False,
            requires_units_style=True,
            lossy_notes=[
                "Per-snapshot ITEM: TIME / simulation-time carries are not written (a dump "
                "time axis needs the run's unit convention, which the write style cannot "
                "verify); step numbers ride ITEM: TIMESTEP (carried or renumbered from 0)."
            ],
        )


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

    # The ATOMS column set: id (carried) · element · type · x y z [vx vy vz] · carried custom
    # columns — image flags excluded in S1 (the pattern above), so what the re-parse carries
    # matches what the write plan promised.
    symbols = list(frame.atoms.symbols)
    positions = np.asarray(frame.atoms.positions, dtype=float) / distance
    custom_values = [
        (key[len(FORMAT_ID) + 1 :], np.asarray(values, dtype=float))
        for key, values in header.custom_per_atom.items()
        if _WRITABLE_PER_ATOM.fullmatch(key)
    ]
    # The id column is written **only when the object carries it** (round-tripped identity);
    # a source without one gets no id column — never a synthesized numbering presented as the
    # source's (P3). The column header and the rows must agree by construction, so the same
    # flag gates both.
    has_velocities = frame.dynamics.velocities is not None
    has_ids = _ID_KEY in header.custom_per_atom
    columns: list[str] = []
    if has_ids:
        columns.append("id")
    columns += ["element", "type", "x", "y", "z"]
    if has_velocities:
        columns += ["vx", "vy", "vz"]
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
        row.append(_fmt(positions[atom_index, 0]))
        row.append(_fmt(positions[atom_index, 1]))
        row.append(_fmt(positions[atom_index, 2]))
        if has_velocities:
            velocity = (
                np.asarray(frame.dynamics.velocities, dtype=float)
                / style.velocity_to_angstrom_per_femtosecond
            )
            row.append(_fmt(velocity[atom_index, 0]))
            row.append(_fmt(velocity[atom_index, 1]))
            row.append(_fmt(velocity[atom_index, 2]))
        for _, values in custom_values:
            if atom_index >= len(values):
                raise ValueError(
                    "lammps_dump: a carried custom column is shorter than the atom count ("
                    f"{len(values)} < {n_atoms})"
                )
            row.append(_fmt_number(values[atom_index]))
        out.append(" ".join(row))
    stream.write(("\n".join(out) + "\n").encode("utf-8"))


def _require_restricted(lattice: np.ndarray, index: int) -> None:
    """A LAMMPS dump can only state the *restricted* triclinic form (edge rows along x). Any
    other cell is refused loudly — rotating a lattice would silently change the trajectory's
    frame of reference, an unrequested transform (D43)."""
    if not (
        np.allclose(lattice[0, 1], 0.0)
        and np.allclose(lattice[0, 2], 0.0)
        and np.allclose(lattice[1, 2], 0.0)
    ):
        raise ValueError(
            "lammps_dump: frame "
            f"{index}'s lattice is not LAMMPS's restricted triclinic form "
            "((a,0,0),(xy,ly,0),(xz,yz,lz)); the format cannot state it — a rotation would "
            "silently change the trajectory's frame of reference"
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
