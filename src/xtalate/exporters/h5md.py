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

**Fields (§4).** Every field the parser maps is written back so the round-trip is lossless:
``velocity``/``force`` (per-step VLEN, canonical units), ``mass`` (u) and ``charge`` (e) (per-step
VLEN, since their length tracks the varying particle count), ``box`` (fixed-in-time when every cell
is identical, time-dependent ``box/edges`` otherwise), ``electronic.total_energy`` →
``/observables/potential_energy`` (eV), and each numeric
``user_metadata.custom_per_frame['h5md:X']`` series → ``/observables/X`` (the ``h5md:`` namespace
stripped, the read prefix undone).

**No silent transformation (P1).** H5MD's canonical spelling *is* Xtalate's — Cartesian coordinates,
eV/Å/fs/u/e — so this exporter converts nothing and applies no sign flip; ``export_warnings`` is the
default empty. Each ``value`` dataset carries a ``unit`` attribute naming the canonical unit, so a
re-parse recovers the units the file declared. What H5MD's per-step-or-nothing layout cannot express
— a field present on only some frames, a periodicity that changes mid-run, a non-numeric per-frame
series — is refused through ``unrepresentable`` rather than silently dropped (P1).

**Streaming.** ``export`` writes a materialized object; the whole-file path is enough for M74's
go/no-go. (An ``export_stream`` that appends VLEN rows frame-by-frame is a later, additive step.)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO, Literal

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
_OBSERVABLE_PREFIX = "h5md:"

_Presence = Literal["all", "none", "mixed"]


def _presence(frames: list[Frame], getter: Callable[[Frame], object | None]) -> _Presence:
    """Whether a per-frame optional field is present on all, none, or only some frames — the fact
    H5MD's per-step-or-nothing layout turns on (a ``mixed`` field is refused via
    :meth:`unrepresentable`, never silently written for a subset)."""
    have = [getter(fr) is not None for fr in frames]
    if all(have):
        return "all"
    if not any(have):
        return "none"
    return "mixed"


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
            if _presence(frames, lambda fr: fr.dynamics.velocities) == "all":
                self._write_vec3(
                    particles, "velocity", frames, lambda fr: fr.dynamics.velocities, "Angstrom/fs"
                )
            if _presence(frames, lambda fr: fr.dynamics.forces) == "all":
                self._write_vec3(
                    particles, "force", frames, lambda fr: fr.dynamics.forces, "eV/Angstrom"
                )
            if _presence(frames, lambda fr: fr.atoms.masses) == "all":
                self._write_scalar_per_atom(
                    particles, "mass", frames, lambda fr: fr.atoms.masses, "u"
                )
            if _presence(frames, lambda fr: fr.electronic.charges) == "all":
                self._write_scalar_per_atom(
                    particles, "charge", frames, lambda fr: fr.electronic.charges, "e"
                )
            self._write_box(particles, frames)
            self._write_observables(f, canonical, frames)

    # -- element writers ---------------------------------------------------------------

    @staticmethod
    def _write_h5md_metadata(f: h5py.File) -> None:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.asarray(_H5MD_VERSION, dtype=np.int64)
        creator = h5md.create_group("creator")
        creator.attrs["name"] = "xtalate"
        creator.attrs["version"] = __version__

    @staticmethod
    def _time_axes(group: h5py.Group, frames: list[Frame]) -> None:
        """Write the ``step``/``time`` datasets shared by every time-dependent element."""
        group.create_dataset("step", data=np.arange(len(frames), dtype=np.int64))
        group.create_dataset(
            "time", data=np.asarray([_frame_time(fr, i) for i, fr in enumerate(frames)])
        )

    def _write_positions(self, particles: h5py.Group, frames: list[Frame]) -> None:
        """``position/{step,time,value}`` with ``value`` a per-step VLEN of flattened (N_t*3,)
        float64 rows — the pinned variable-N mechanism (D-DEP)."""
        group = particles.create_group("position")
        value = group.create_dataset(
            "value", shape=(len(frames),), dtype=h5py.vlen_dtype(np.float64)
        )
        for i, frame in enumerate(frames):
            value[i] = np.asarray(frame.atoms.positions, dtype=np.float64).reshape(-1)
        value.attrs["unit"] = "Angstrom"
        self._time_axes(group, frames)

    def _write_species(self, particles: h5py.Group, frames: list[Frame]) -> None:
        """``species/{step,time,value}`` with ``value`` a per-step VLEN of int atomic numbers —
        time-dependent because the particle count (and thus the row length) varies per frame."""
        group = particles.create_group("species")
        value = group.create_dataset("value", shape=(len(frames),), dtype=h5py.vlen_dtype(np.int64))
        for i, frame in enumerate(frames):
            value[i] = np.asarray(frame.atoms.atomic_numbers, dtype=np.int64)
        self._time_axes(group, frames)

    def _write_vec3(
        self,
        particles: h5py.Group,
        name: str,
        frames: list[Frame],
        getter: Callable[[Frame], object | None],
        unit: str,
    ) -> None:
        """A per-atom 3-vector element (velocity, force) as a per-step VLEN of (N_t*3,) float64."""
        group = particles.create_group(name)
        value = group.create_dataset(
            "value", shape=(len(frames),), dtype=h5py.vlen_dtype(np.float64)
        )
        for i, frame in enumerate(frames):
            value[i] = np.asarray(getter(frame), dtype=np.float64).reshape(-1)
        value.attrs["unit"] = unit
        self._time_axes(group, frames)

    def _write_scalar_per_atom(
        self,
        particles: h5py.Group,
        name: str,
        frames: list[Frame],
        getter: Callable[[Frame], object | None],
        unit: str,
    ) -> None:
        """A per-atom scalar element (mass, charge) as a per-step VLEN of (N_t,) float64 — kept
        time-dependent so its length tracks each frame's own particle count."""
        group = particles.create_group(name)
        value = group.create_dataset(
            "value", shape=(len(frames),), dtype=h5py.vlen_dtype(np.float64)
        )
        for i, frame in enumerate(frames):
            value[i] = np.asarray(getter(frame), dtype=np.float64).reshape(-1)
        value.attrs["unit"] = unit
        self._time_axes(group, frames)

    def _write_box(self, particles: h5py.Group, frames: list[Frame]) -> None:
        """``box/edges`` — a fixed-in-time 3×3 dataset when every frame shares one cell, a
        time-dependent ``{step,time,value}`` (value ``[T,3,3]``) when the cell varies — plus a
        ``boundary`` vector from ``cell.pbc``. A trajectory without any cell writes no box (P3)."""
        if _presence(frames, lambda fr: fr.cell) != "all":
            return  # no cell, or a mixed trajectory already refused by unrepresentable
        cells = [fr.cell for fr in frames]
        box = particles.create_group("box")
        box.attrs["dimension"] = np.int64(3)
        lattices = [np.asarray(c.lattice_vectors, dtype=np.float64) for c in cells]  # type: ignore[union-attr]
        if all(np.array_equal(m, lattices[0]) for m in lattices):
            box.create_dataset("edges", data=lattices[0])
        else:
            edges = box.create_group("edges")
            edges.create_dataset("value", data=np.stack(lattices))
            self._time_axes(edges, frames)
        boundary = [b"periodic" if p else b"none" for p in cells[0].pbc]  # type: ignore[union-attr]
        box.create_dataset("boundary", data=np.asarray(boundary))

    def _write_observables(
        self, f: h5py.File, canonical: CanonicalObject, frames: list[Frame]
    ) -> None:
        """``electronic.total_energy`` → ``/observables/potential_energy`` (eV); each numeric
        ``custom_per_frame['h5md:X']`` series → ``/observables/X`` (the read prefix undone)."""
        series: list[tuple[str, np.ndarray, str | None]] = []
        if _presence(frames, lambda fr: fr.electronic.total_energy) == "all":
            energies = np.asarray([fr.electronic.total_energy for fr in frames], dtype=np.float64)
            series.append(("potential_energy", energies, "eV"))
        for key, val in canonical.user_metadata.custom_per_frame.items():
            name = key[len(_OBSERVABLE_PREFIX) :] if key.startswith(_OBSERVABLE_PREFIX) else key
            series.append((name, np.asarray(val, dtype=np.float64), None))
        if not series:
            return
        obs = f.create_group("observables")
        for name, values, unit in series:
            group = obs.create_group(name)
            value = group.create_dataset("value", data=values)
            if unit is not None:
                value.attrs["unit"] = unit
            self._time_axes(group, frames)

    # -- transformations & value-level representability --------------------------------

    def unrepresentable(self, canonical: CanonicalObject) -> str | None:
        """Why H5MD cannot hold this object's *values* (Part 4 §1; DECISIONS.md D179), or ``None``.

        H5MD holds a time-dependent element for every step or not at all, so a per-frame field
        present on only *some* frames, a periodicity that changes between frames, or a non-numeric
        per-frame series cannot be written — refused here rather than silently dropped (P1)."""
        frames = canonical.frames
        for label, getter in (
            ("velocities", lambda fr: fr.dynamics.velocities),
            ("forces", lambda fr: fr.dynamics.forces),
            ("masses", lambda fr: fr.atoms.masses),
            ("charges", lambda fr: fr.electronic.charges),
            ("a total energy", lambda fr: fr.electronic.total_energy),
            ("a simulation cell", lambda fr: fr.cell),
        ):
            if _presence(frames, getter) == "mixed":
                return (
                    f"H5MD writes {label} for every frame or none; this trajectory carries it on "
                    "some frames but not others, which the per-step layout cannot express."
                )
        cells = [fr.cell for fr in frames if fr.cell is not None]
        if cells and any(c.pbc != cells[0].pbc for c in cells):
            return (
                "H5MD's box boundary is fixed for the whole trajectory, but this one changes its "
                "periodicity between frames."
            )
        for key, val in canonical.user_metadata.custom_per_frame.items():
            if not isinstance(val, np.ndarray):
                return (
                    f"H5MD stores a per-frame observable as a numeric dataset, but "
                    f"custom_per_frame[{key!r}] is non-numeric and cannot be written."
                )
        return None

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
                "atoms.masses": full,
                "dynamics.velocities": full,
                "dynamics.forces": full,
                "electronic.charges": full,
                "electronic.total_energy": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Written to /observables/potential_energy."
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Written as box/edges (fixed-in-time or per step) when a cell exists.",
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
