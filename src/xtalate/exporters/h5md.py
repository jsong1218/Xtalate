"""H5MD (HDF5-for-molecular-data) exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v2.0 M74).

The mirror of ``parsers.h5md``: it writes a Canonical Object into one H5MD file — the community
HDF5 layout for molecular data — through ``h5py``. H5MD is the eighth first-party format and the
one that proves the M72/M73 variable-N engines against a real binary container: a trajectory whose
atom count differs per frame is written natively, never narrowed to a constant-N slice.

**The variable-N write mechanism (pinned S1, DECISIONS.md D-DEP).** A time-dependent element in
H5MD is a ``{step, time, value}`` triple; for a constant-N trajectory ``value`` is a plain
``[T, N, D]`` dataset, but that shape cannot hold frames of differing N. The chosen mechanism is a
**per-step variable-length (VLEN) dataset**: ``position/value`` is a length-T VLEN array of float64,
each entry that frame's positions flattened to ``(N_t * 3,)``, and ``species/value`` a length-T
VLEN array of int, each entry that frame's atomic numbers ``(N_t,)``. The particle dimension is thus
free to vary per step. The rejected alternative — one HDF5 dataset per step under a numbered group —
multiplies HDF5 objects with frame count and reads back as a bag of datasets the streaming parser
would have to sort and stitch; the VLEN layout keeps one dataset per element and one row per frame.

**Streaming.** ``export`` writes a materialized object; the whole-file path is enough for M74's
go/no-go. (An ``export_stream`` that appends VLEN rows frame-by-frame is a later, additive step.)

Fields H5MD cannot express are the Conversion Engine's to report as ``removed`` — this exporter
writes exactly what the object holds and fabricates nothing for absent fields (Part 4 §1 rule 2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

import h5py
import numpy as np

from xtalate import __version__
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
)

if TYPE_CHECKING:
    from xtalate.schema import CanonicalObject, Frame

FORMAT_ID = "h5md"
_PARTICLE_GROUP = "all"
# The H5MD spec version this exporter targets (major, minor). Written under /h5md as required.
_H5MD_VERSION = (1, 1)


class H5MDExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "H5MD"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        frames = canonical.frames
        with h5py.File(stream, "w") as f:
            self._write_h5md_metadata(f)
            particles = f.create_group(f"particles/{_PARTICLE_GROUP}")
            self._write_positions(particles, frames)
            self._write_species(particles, frames)
            self._write_box(particles, frames)

    # -- element writers ---------------------------------------------------------------

    @staticmethod
    def _write_h5md_metadata(f: h5py.File) -> None:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.asarray(_H5MD_VERSION, dtype=np.int64)
        creator = h5md.create_group("creator")
        creator.attrs["name"] = "xtalate"
        creator.attrs["version"] = __version__

    @staticmethod
    def _write_positions(particles: h5py.Group, frames: list[Frame]) -> None:
        """``position/{step,time,value}`` with ``value`` a per-step VLEN of flattened (N_t*3,)
        float64 rows — the pinned variable-N mechanism (D-DEP)."""
        group = particles.create_group("position")
        vlen = h5py.vlen_dtype(np.float64)
        value = group.create_dataset("value", shape=(len(frames),), dtype=vlen)
        for i, frame in enumerate(frames):
            value[i] = np.asarray(frame.atoms.positions, dtype=np.float64).reshape(-1)
        group.create_dataset("step", data=np.arange(len(frames), dtype=np.int64))
        group.create_dataset(
            "time", data=np.asarray([_frame_time(fr, i) for i, fr in enumerate(frames)])
        )

    @staticmethod
    def _write_species(particles: h5py.Group, frames: list[Frame]) -> None:
        """``species/{step,time,value}`` with ``value`` a per-step VLEN of int atomic numbers —
        time-dependent because the particle count (and thus the row length) varies per frame."""
        group = particles.create_group("species")
        vlen = h5py.vlen_dtype(np.int64)
        value = group.create_dataset("value", shape=(len(frames),), dtype=vlen)
        for i, frame in enumerate(frames):
            value[i] = np.asarray(frame.atoms.atomic_numbers, dtype=np.int64)
        group.create_dataset("step", data=np.arange(len(frames), dtype=np.int64))
        group.create_dataset(
            "time", data=np.asarray([_frame_time(fr, i) for i, fr in enumerate(frames)])
        )

    @staticmethod
    def _write_box(particles: h5py.Group, frames: list[Frame]) -> None:
        """``box/edges`` as a fixed-in-time 3×3 dataset when every frame shares one cell, plus a
        ``boundary`` vector from ``cell.pbc``. A frame without a cell writes no box (absence, P3).
        """
        cells = [fr.cell for fr in frames if fr.cell is not None]
        if not cells:
            return
        first = cells[0]
        box = particles.create_group("box")
        box.attrs["dimension"] = np.int64(3)
        box.create_dataset("edges", data=np.asarray(first.lattice_vectors, dtype=np.float64))
        boundary = [b"periodic" if p else b"none" for p in first.pbc]
        box.create_dataset("boundary", data=np.asarray(boundary))

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Written as box/edges when a cell is present.",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL, notes="Written as box/boundary."
                ),
            },
            max_frames=None,
            # H5MD stores each step's particle dimension independently, so a variable-N trajectory
            # is written natively (v2.0 M74) — no frame_selection recovery needed on this target.
            supports_variable_atom_count=True,
            required_fields=["atoms.symbols", "atoms.positions"],
            allows_open_boundaries=True,
            native_coordinate_system="cartesian",
        )


def _frame_time(frame: Frame, index: int) -> float:
    """A frame's absolute time when the source stated it, else its index as the step-time — H5MD
    requires a ``time`` dataset alongside ``step`` even when the source declared none."""
    return float(frame.time) if frame.time is not None else float(index)


def make_h5md_exporter() -> H5MDExporter:
    return H5MDExporter()
