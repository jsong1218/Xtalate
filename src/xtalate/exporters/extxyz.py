"""Extended XYZ exporter (MASTER_SPEC Part 3 §2, Part 4 §1).

The mirror of ``parsers.extxyz``: it rebuilds an ASE ``Atoms`` per frame from the Canonical
Object and lets ASE serialise the ``Lattice=`` / ``Properties=`` grammar. Every mapping is the
exact inverse of the parser's (DECISIONS.md D18), including the velocity unit conversion
(canonical Å/fs → ASE internal units) so that ``A → Canonical → A' → Canonical'`` reproduces
the scientific content exactly. Fields extXYZ cannot express are the Conversion Engine's to
report as ``removed`` (Part 4); this exporter simply writes what the object holds.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from typing import Any, BinaryIO

import numpy as np
from ase import Atoms
from ase import units as ase_units
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import write as ase_write

from xtalate.schema import CanonicalObject, Frame
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    StreamFrame,
    StreamHeader,
)

FORMAT_ID = "extxyz"
_KEY_PREFIX = "extxyz:"
_STRESS_KEY = "extxyz:stress"
# The per-atom custom keys extXYZ can write *and* read back under the same name (D69). Declared to
# the pre-flight as `writable_custom_key_pattern` and compiled here for the exporter's own guard,
# from this single string so the declaration and the behaviour cannot drift apart.
_WRITABLE_PER_ATOM_PATTERN = rf"{_KEY_PREFIX}[^:]*"
_WRITABLE_PER_ATOM_KEY = re.compile(_WRITABLE_PER_ATOM_PATTERN)
# The velocity conversion factor in units of (Å/fs) per one ASE internal velocity unit — i.e.
# `ase_units.fs`. Named for its units so the export direction reads correctly: canonical Å/fs
# *divided by* this factor yields ASE units (the exact inverse of the parser's multiply). Defined
# here (not imported from parsers) because exporters and parsers are import-sibling layers that must
# not depend on each other (pyproject import-linter contract, P2).
_ANG_PER_FS_PER_ASE_VEL = ase_units.fs


class ExtxyzExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "Extended XYZ"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        custom_per_atom = canonical.user_metadata.custom_per_atom
        per_frame = canonical.user_metadata.custom_per_frame
        images = [
            self._atoms_from(
                frame,
                custom_per_atom,
                {
                    key: (values[frame.index] if frame.index < len(values) else None)
                    for key, values in per_frame.items()
                },
            )
            for frame in canonical.frames
        ]
        buf = io.StringIO()
        ase_write(buf, images, format="extxyz")
        stream.write(buf.getvalue().encode("utf-8"))

    def supports_streaming(self) -> bool:
        return True

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        """Write each frame's extXYZ block as it arrives (M12), holding at most one frame resident.

        ASE serialises each ``Atoms`` as an independent extXYZ block (count, comment, atom rows), so
        writing images one at a time and concatenating is byte-identical to a single whole-list
        write — the streamed output matches ``export`` exactly. The object-level ``custom_per_atom``
        columns ride on the header and apply to every frame; the per-frame comment metadata rides on
        each ``StreamFrame``."""
        for sf in frames:
            atoms = self._atoms_from(sf.frame, header.custom_per_atom, sf.per_frame_custom)
            buf = io.StringIO()
            ase_write(buf, atoms, format="extxyz")
            stream.write(buf.getvalue().encode("utf-8"))

    def _atoms_from(
        self,
        frame: Frame,
        custom_per_atom: dict[str, Any],
        per_frame_custom: dict[str, Any],
    ) -> Atoms:
        """Rebuild one ASE ``Atoms`` from a canonical frame plus its object-level per-atom columns
        and this frame's per-frame comment metadata. Shared by whole-file ``export`` and streaming
        ``export_stream`` so the two paths can never write a frame differently."""
        atoms = Atoms(
            symbols=list(frame.atoms.symbols),
            positions=np.asarray(frame.atoms.positions, dtype=float),
        )
        if frame.atoms.masses is not None:
            atoms.set_masses(np.asarray(frame.atoms.masses, dtype=float))
        if frame.cell is not None:
            atoms.set_cell(np.asarray(frame.cell.lattice_vectors, dtype=float))
            atoms.set_pbc(frame.cell.pbc)
        if frame.dynamics.velocities is not None:
            v_ase = np.asarray(frame.dynamics.velocities, dtype=float) / _ANG_PER_FS_PER_ASE_VEL
            atoms.set_velocities(v_ase)

        # Object-level per-atom carry-through columns apply to every frame (Part 2 §3.10), but only
        # under a name the Properties= grammar can spell (D69). The pre-flight has normally already
        # dropped the rest, so this filter usually removes nothing; it is here because `export` is
        # also called directly, outside the engine, and a foreign key written here does not degrade
        # the output — it makes the file unparseable.
        for key, values in custom_per_atom.items():
            if _WRITABLE_PER_ATOM_KEY.fullmatch(key):
                atoms.new_array(_strip(key), np.asarray(values))

        # Per-frame comment key-values (+ stress) for this frame.
        stress = None
        for key, value in per_frame_custom.items():
            if value is None:
                continue
            if key == _STRESS_KEY:
                stress = np.asarray(value, dtype=float)
            else:
                atoms.info[_strip(key)] = value

        results: dict[str, Any] = {}
        if frame.electronic.total_energy is not None:
            results["energy"] = float(frame.electronic.total_energy)
        if frame.dynamics.forces is not None:
            results["forces"] = np.asarray(frame.dynamics.forces, dtype=float)
        if frame.electronic.charges is not None:
            results["charges"] = np.asarray(frame.electronic.charges, dtype=float)
        if frame.electronic.magnetic_moments is not None:
            results["magmoms"] = np.asarray(frame.electronic.magnetic_moments, dtype=float)
        if stress is not None:
            results["stress"] = stress
        if results:
            atoms.calc = SinglePointCalculator(atoms, **results)
        return atoms

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        partial = CapabilityLevel.PARTIAL
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "atoms.masses": FieldCapability(level=partial, notes="Written as a masses column."),
                "cell.lattice_vectors": FieldCapability(
                    level=partial, notes="Written as the Lattice= key when a cell is present."
                ),
                "cell.pbc": FieldCapability(level=partial, notes="Written as the pbc= key."),
                "dynamics.velocities": FieldCapability(
                    level=partial, notes="Written as a momenta column; unit-converted."
                ),
                "dynamics.forces": FieldCapability(
                    level=partial, notes="Written as a forces column."
                ),
                "electronic.total_energy": FieldCapability(
                    level=partial, notes="Written as the energy= key."
                ),
                "electronic.charges": FieldCapability(
                    level=partial, notes="Written as a per-atom charge column."
                ),
                "electronic.magnetic_moments": FieldCapability(
                    level=partial, notes="Written as a per-atom magmoms column."
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Written back as Properties= columns, but only under a name extXYZ can "
                    "spell: the Properties= grammar separates its fields with ':', so a "
                    "format-scoped key such as 'cif:occupancy' cannot be written at all, and a "
                    "bare name is read back re-prefixed as 'extxyz:<name>'. Keys matching "
                    "'extxyz:<name>' round-trip exactly; the rest are dropped (DECISIONS.md D69).",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Written back as comment key-values."
                ),
            },
            # Open-ended by design — extXYZ's arbitrary columns are why anyone reaches for it — so
            # the writable set is a name *pattern*, not a list (D69). Per-frame keys need no
            # pattern: they ride the comment line's key=value grammar, where a colon is legal.
            writable_custom_key_pattern={
                "user_metadata.custom_per_atom": _WRITABLE_PER_ATOM_PATTERN
            },
            max_frames=None,
            required_fields=["atoms.symbols", "atoms.positions"],
            allows_open_boundaries=True,  # extXYZ writes pbc=; an open cell is expressible.
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )


def _strip(key: str) -> str:
    """``'extxyz:foo'`` → ``'foo'``; a user/plugin key without the prefix is written as-is."""
    return key[len(_KEY_PREFIX) :] if key.startswith(_KEY_PREFIX) else key
