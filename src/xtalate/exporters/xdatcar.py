"""VASP XDATCAR exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v0.3 M13).

Writes a multi-configuration trajectory in VASP's **Direct** (fractional) convention — the
format's only convention in practice, so honesty about what VASP will actually read outweighs
the exactness argument that made POSCAR write Cartesian with a unit scale (DECISIONS.md D8).
Cartesian canonical positions are therefore converted back to fractional against each frame's
lattice on write; the resulting sub-ulp inversion error is a *declared* representational
bound (``numeric_precision``), not a silent one, and the Validation Engine holds the output to
it (Part 5 §4.2).

**Both cell forms, decided single-pass.** The header is written once, and a frame whose cell
differs from the previous frame's restates the whole header ahead of its configuration — VASP's
NpT form. That one rule produces the compact fixed-cell file when the cell never moves and the
restating NpT file when it always does, without ever needing to look ahead at frames not yet
read. This is what lets ``export_stream`` write a 10⁴-frame trajectory with one frame resident
(M12; DECISIONS.md D56) while still exporting a per-frame cell faithfully rather than
collapsing an NpT run onto frame 0's lattice — which would be exactly the silent loss the
mission forbids (P1).

**Streaming-first**, mirroring the parser: ``export`` is defined as ``export_stream`` over the
materialized object's frames, so the whole-file and streamed writings are one code path and
cannot diverge.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

import numpy as np

from xtalate.exporters._common import group_by_element
from xtalate.schema import CanonicalObject, Frame
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
)
from xtalate.sdk.streaming import StreamFrame, StreamHeader, stream_of

FORMAT_ID = "xdatcar"

_COMMENT_KEY = "xdatcar:comment"


def _fmt(x: float) -> str:
    return repr(float(x))


def _to_fractional(positions: np.ndarray, lattice: np.ndarray) -> np.ndarray:
    """Cartesian Å → Direct (fractional) against ``lattice`` (rows a, b, c).

    ``cart = frac @ lattice``, so ``frac`` solves ``lattice.T @ frac.T = cart.T``. Solved rather
    than multiplied by an explicit inverse: for the skewed cells MD cells routinely become, a
    solve is the better-conditioned of the two and keeps the round-trip error at the ulp level
    the declared precision bound assumes.
    """
    return np.linalg.solve(lattice.T, positions.T).T


class XdatcarExporter(ExporterPlugin):
    """VASP XDATCAR writer (Part 3 §3)."""

    version = "0.1.0"

    def __init__(self) -> None:
        self.format_id = FORMAT_ID
        self.format_name = "VASP XDATCAR"

    def atom_permutation(self, canonical: CanonicalObject) -> list[int] | None:
        """The element-grouping reorder this exporter applies on write (Part 5 §2), reconstructed
        from the same ``group_by_element`` ``export`` writes with. ``None`` when the source order
        already groups by element and no reordering happens."""
        permutation = group_by_element(canonical.frames[0].atoms.symbols)[1]
        return None if permutation == list(range(len(permutation))) else permutation

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        """Whole-file write, defined as the streamed write over the object's own frames — so a
        streamed and a materialized XDATCAR export are the same code (D56), never two paths that
        must be kept in step."""
        frame_stream = stream_of(canonical)
        self.export_stream(frame_stream.header, frame_stream.frames(), stream)

    def supports_streaming(self) -> bool:
        return True

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        title = header.custom_global.get(_COMMENT_KEY, "")
        title_line = str(title) if title is not None else ""

        previous_lattice: np.ndarray | None = None
        order: list[str] | None = None
        permutation: list[int] = []
        counts: list[int] = []

        for i, sf in enumerate(frames):
            frame = sf.frame
            lattice = _require_cell(frame, i)
            if order is None:
                order, permutation, counts = group_by_element(list(frame.atoms.symbols))

            # The header is restated whenever the cell moves (VASP's NpT form) and written once
            # up front otherwise. Comparing against the *previous* frame — not frame 0 — is what
            # makes the rule single-pass and correct for both forms.
            if previous_lattice is None or not np.array_equal(lattice, previous_lattice):
                _write_header(stream, title_line, lattice, order, counts)
            previous_lattice = lattice

            stream.write(f"Direct configuration=  {i + 1:>5}\n".encode())
            frac = _to_fractional(
                np.asarray(frame.atoms.positions, dtype=float), np.asarray(lattice, dtype=float)
            )
            for atom_idx in permutation:
                row = frac[atom_idx]
                stream.write(f"  {_fmt(row[0])} {_fmt(row[1])} {_fmt(row[2])}\n".encode())

        if order is None:
            raise ValueError(
                "XDATCAR holds at least one configuration; the object being exported has no frames"
            )

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        none = FieldCapability(level=CapabilityLevel.NONE)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "atoms.masses": none,
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="A per-frame cell is written by restating the header ahead of a "
                    "configuration whose cell moved (the NpT form), so an NpT trajectory is not "
                    "collapsed onto one lattice.",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only fully periodic (T,T,T); other PBC combinations cannot be "
                    "represented.",
                ),
                "cell.space_group": none,
                # XDATCAR is positions-over-time and nothing else: it has no velocity block (that
                # is CONTCAR's), no forces, no constraints, no energies.
                "dynamics.velocities": none,
                "dynamics.forces": none,
                "dynamics.constraints": none,
                "electronic.total_energy": none,
                "electronic.stress": none,
                "electronic.charges": none,
                "electronic.magnetic_moments": none,
                "simulation.*": none,
                "trajectory.timestep": none,
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only the XDATCAR title (xdatcar:comment); other custom_global keys are "
                    "dropped.",
                ),
                "user_metadata.custom_per_atom": none,
                "user_metadata.custom_per_frame": none,
            },
            max_frames=None,  # the point of the format: an unbounded configuration count
            required_fields=["atoms.symbols", "atoms.positions", "cell.lattice_vectors"],
            allows_open_boundaries=False,  # XDATCAR cells are fully periodic (Part 3 §4.2).
            representable_constraint_kinds=[],
            writable_custom_keys={"user_metadata.custom_global": [_COMMENT_KEY]},
            native_coordinate_system="fractional",
            lossy_notes=[
                "Positions are written in VASP's Direct (fractional) convention, so a Cartesian "
                "source round-trips through a lattice inversion; agreement is exact to within "
                "float64 rounding, not bit-for-bit."
            ],
        )


def _require_cell(frame: Frame, index: int) -> Any:
    if frame.cell is None:
        raise ValueError(
            f"XDATCAR requires cell.lattice_vectors and frame {index} has none; supply it via the "
            "missing_lattice recovery before export (Part 4 §3)"
        )
    return frame.cell.lattice_vectors


def _write_header(
    stream: BinaryIO,
    title: str,
    lattice: Any,
    order: list[str],
    counts: list[int],
) -> None:
    """The 7-line VASP header: title, scale, three lattice rows, species, counts.

    The scale is written as ``1.0`` because canonical lattice vectors are already absolute Å —
    the same choice POSCAR makes (D8), and the reason a parsed scale is a provenance note rather
    than a field to carry (D34).
    """
    out = [title, "1.0"]
    for row in np.asarray(lattice, dtype=float):
        out.append(f"  {_fmt(row[0])} {_fmt(row[1])} {_fmt(row[2])}")
    out.append(" ".join(order))
    out.append(" ".join(str(c) for c in counts))
    stream.write(("\n".join(out) + "\n").encode("utf-8"))


def make_xdatcar_exporter() -> XdatcarExporter:
    return XdatcarExporter()
