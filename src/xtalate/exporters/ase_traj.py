"""ASE trajectory (``.traj``) exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v0.3 M14).

The mirror of ``parsers.ase_traj``: it rebuilds an ASE ``Atoms`` per frame from the Canonical
Object and lets ASE serialise its ULM ``.traj`` container. Every mapping is the exact inverse of
the parser's (DECISIONS.md D18), including the velocity unit conversion (canonical Å/fs → ASE
internal units) and the charge/moment routing (``electronic.charges`` → ASE ``initial_charges``),
so ``A → Canonical → A' → Canonical'`` reproduces the scientific content exactly.

**Streaming-first.** ``export_stream`` writes each frame to the output as it arrives (ASE's
``TrajectoryWriter`` flushes per frame), holding at most one frame resident; ``export`` is the same
per-frame write over a materialized object. Fields ``.traj`` cannot express are the Conversion
Engine's to report as ``removed`` — this exporter simply writes what the object holds (Part 4 §1).

``ase.units.fs`` is redefined locally rather than imported from the parser: exporters and parsers
are import-sibling layers that must not depend on each other (import-linter P2 contract), the same
reason ``exporters.extxyz`` redefines its own velocity constant.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

import numpy as np
from ase import Atoms
from ase import units as ase_units
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixAtoms
from ase.io.trajectory import TrajectoryWriter

from xtalate.schema import CanonicalObject, Frame
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    StreamFrame,
    StreamHeader,
)

FORMAT_ID = "ase_traj"
_KEY_PREFIX = "ase_traj:"
_STRESS_KEY = "ase_traj:stress"
_CONSTRAINTS_KEY = "ase_traj:constraints"
# (Å/fs) per one ASE internal velocity unit — i.e. ase_units.fs. Canonical Å/fs *divided by* this
# yields ASE units (the exact inverse of the parser's multiply). Defined here, not imported, so the
# exporter layer does not depend on the parser layer (P2; mirrors exporters.extxyz).
_ANG_PER_FS_PER_ASE_VEL = ase_units.fs


class AseTrajExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "ASE Trajectory"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        custom_per_atom = canonical.user_metadata.custom_per_atom
        per_frame = canonical.user_metadata.custom_per_frame
        writer = TrajectoryWriter(stream, "w")
        for frame in canonical.frames:
            row = {
                key: (values[frame.index] if frame.index < len(values) else None)
                for key, values in per_frame.items()
            }
            writer.write(self._atoms_from(frame, custom_per_atom, row))
        # Deliberately not closed: TrajectoryWriter.close() would close the caller's stream, and ULM
        # flushes each frame on write, so the output is already complete (M14; verified round-trip).

    def supports_streaming(self) -> bool:
        return True

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        """Write each frame's ULM block as it arrives (M12/M14), holding at most one frame resident.
        The object-level ``custom_per_atom`` columns ride on the header; per-frame comment metadata
        rides on each ``StreamFrame``. Not closed, for the same reason as ``export``."""
        writer = TrajectoryWriter(stream, "w")
        for sf in frames:
            writer.write(self._atoms_from(sf.frame, header.custom_per_atom, sf.per_frame_custom))

    def _atoms_from(
        self,
        frame: Frame,
        custom_per_atom: dict[str, Any],
        per_frame_custom: dict[str, Any],
    ) -> Atoms:
        """Rebuild one ASE ``Atoms`` from a canonical frame plus its object-level per-atom columns
        and this frame's per-frame comment metadata. Shared by ``export`` and ``export_stream`` so
        the two paths can never write a frame differently."""
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
        # electronic.charges/magmoms round-trip through ASE's per-atom initial_* arrays (the parser
        # reads them from there); the exporter writes them back to the same place.
        if frame.electronic.charges is not None:
            atoms.set_initial_charges(np.asarray(frame.electronic.charges, dtype=float))
        if frame.electronic.magnetic_moments is not None:
            atoms.set_initial_magnetic_moments(
                np.asarray(frame.electronic.magnetic_moments, dtype=float)
            )
        self._apply_constraints(atoms, frame)

        # Object-level per-atom carry-through columns are *not* written: the ULM trajectory writer
        # discards every custom array regardless of name, so setting them here would produce an
        # object whose arrays silently vanish on the way to disk (D69). Declared NONE, reported
        # `removed`, and not set at all — so the code says the same thing the capability does.
        _ = custom_per_atom

        # Per-frame comment key-values (+ stress) for this frame.
        stress = None
        for key, value in per_frame_custom.items():
            if value is None:
                continue
            if key == _STRESS_KEY:
                stress = np.asarray(value, dtype=float)
            elif key == _CONSTRAINTS_KEY:
                continue  # carried-through non-FixAtoms constraint text; not re-materialisable
            else:
                atoms.info[_strip(key)] = value

        results: dict[str, Any] = {}
        if frame.electronic.total_energy is not None:
            results["energy"] = float(frame.electronic.total_energy)
        if frame.dynamics.forces is not None:
            results["forces"] = np.asarray(frame.dynamics.forces, dtype=float)
        if stress is not None:
            results["stress"] = stress
        if results:
            atoms.calc = SinglePointCalculator(atoms, **results)
        return atoms

    @staticmethod
    def _apply_constraints(atoms: Atoms, frame: Frame) -> None:
        """Write ``fixed_atoms`` constraints back as ASE ``FixAtoms``. An empty/``None`` constraint
        list leaves ASE's default (no constraint); an unrepresentable kind is the Conversion
        Engine's to report as ``removed`` — this exporter writes only what it can express."""
        constraints = frame.dynamics.constraints
        if not constraints:
            return
        fixed: list[int] = []
        for con in constraints:
            if con.kind == "fixed_atoms":
                fixed.extend(int(i) for i in con.atom_indices)
        if fixed:
            atoms.set_constraint(FixAtoms(indices=sorted(set(fixed))))

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
                "atoms.masses": FieldCapability(level=partial, notes="Written as a masses array."),
                "cell.lattice_vectors": FieldCapability(
                    level=partial, notes="Written when a cell is present."
                ),
                "cell.pbc": FieldCapability(level=partial, notes="Written alongside the cell."),
                "dynamics.velocities": FieldCapability(
                    level=partial, notes="Written as momenta; unit-converted."
                ),
                "dynamics.forces": FieldCapability(
                    level=partial, notes="Written on the calculator."
                ),
                "dynamics.constraints": FieldCapability(
                    level=partial, notes="Only fixed_atoms (→ ASE FixAtoms); other kinds dropped."
                ),
                "electronic.total_energy": FieldCapability(
                    level=partial, notes="Written on the calculator."
                ),
                "electronic.charges": FieldCapability(
                    level=partial, notes="Written as the initial_charges array."
                ),
                "electronic.magnetic_moments": FieldCapability(
                    level=partial, notes="Written as the initial_magmoms array."
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.NONE,
                    notes="ASE's .traj writer persists no custom per-atom array — not under a "
                    "format-scoped name, not under a plain one — so a carry-through column cannot "
                    "be written at all. Per-frame metadata (atoms.info) is unaffected.",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Written back as atoms.info key-values."
                ),
            },
            max_frames=None,
            required_fields=["atoms.symbols", "atoms.positions"],
            allows_open_boundaries=True,  # ASE writes pbc; an open cell is expressible.
            representable_constraint_kinds=["fixed_atoms"],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )


def _strip(key: str) -> str:
    """``'ase_traj:foo'`` → ``'foo'``; a key without the prefix is written as-is."""
    return key[len(_KEY_PREFIX) :] if key.startswith(_KEY_PREFIX) else key


def make_ase_traj_exporter() -> AseTrajExporter:
    return AseTrajExporter()
