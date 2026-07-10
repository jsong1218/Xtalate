"""VASP POSCAR / CONTCAR exporter (MASTER_SPEC Part 3 §3, Part 4 §1, §8.2).

Writes a single-structure POSCAR. Coordinates are emitted in **Cartesian** mode with a
scaling factor of ``1.0`` (canonical lattice vectors are already absolute Å), so a
parsed→exported→parsed round-trip reproduces the Cartesian positions exactly with no matrix
inversion (DECISIONS.md D8). POSCAR requires atoms of one element to be contiguous, so the
exporter **groups by element** in first-occurrence order; that grouping is a permutation of
the atom list (the same permutation Part 5 validation reconstructs) applied consistently to
positions, velocities, and selective-dynamics masks. A CONTCAR velocity / predictor-corrector
tail carried through on parse is written back so CONTCAR identity round-trips.

Multi-frame input is refused here rather than silently truncated: reducing a trajectory to
one structure is a *selective-reductive* choice the Conversion Engine records as an
Assumption before it ever calls this exporter (Part 4 §3).
"""

from __future__ import annotations

from typing import BinaryIO

from chembridge.schema import CanonicalObject
from chembridge.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
)

_COMMENT_KEY = "poscar:comment"
_PREDICTOR_KEY = "contcar:predictor_corrector"


def _fmt(x: float) -> str:
    return repr(float(x))


def _grouping(symbols: list[str]) -> tuple[list[str], list[int], list[int]]:
    """Group atoms by element in first-occurrence order (POSCAR requires one element's atoms to be
    contiguous). Returns ``(order, permutation, counts)`` where ``order`` is the element sequence,
    ``permutation[i]`` is the source index written at output position *i* (the Part 5 permutation
    map), and ``counts`` is the per-element atom count. Used by both ``export`` (to write the file)
    and ``atom_permutation`` (to report the map), so the two can never disagree."""
    order: list[str] = []
    groups: dict[str, list[int]] = {}
    for i, sym in enumerate(symbols):
        if sym not in groups:
            groups[sym] = []
            order.append(sym)
        groups[sym].append(i)
    permutation = [i for sym in order for i in groups[sym]]
    counts = [len(groups[sym]) for sym in order]
    return order, permutation, counts


class PoscarExporter(ExporterPlugin):
    """POSCAR/CONTCAR writer. One class, registered under ``poscar`` and ``contcar``
    (the canonical fields written are identical; only the reported label differs)."""

    version = "0.1.0"

    def __init__(self, *, format_id: str = "poscar") -> None:
        self.format_id = format_id
        self.format_name = "VASP POSCAR" if format_id == "poscar" else "VASP CONTCAR"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        if len(canonical.frames) != 1:
            raise ValueError(
                "POSCAR holds a single structure; reduce the trajectory to one frame via the "
                "Conversion Engine's frame_selection recovery before export (Part 4 §3)"
            )
        frame = canonical.frames[0]
        atoms = frame.atoms
        cell = frame.cell
        if cell is None:
            raise ValueError(
                "POSCAR requires cell.lattice_vectors; supply it via the missing_lattice "
                "recovery before export (Part 4 §3)"
            )

        # Group atoms by element in first-occurrence order -> a permutation applied to every
        # per-atom array so the written file is internally consistent (Part 5 permutation map).
        order, permutation, counts = _grouping(atoms.symbols)

        title = canonical.user_metadata.custom_global.get(_COMMENT_KEY, "")
        out: list[str] = [str(title) if title is not None else ""]
        out.append("1.0")  # canonical lattice is absolute; no rescale needed
        for row in cell.lattice_vectors:
            out.append(f"  {_fmt(row[0])} {_fmt(row[1])} {_fmt(row[2])}")
        out.append(" ".join(order))
        out.append(" ".join(str(c) for c in counts))

        # Selective dynamics: present (even all-T) => write the block so [] round-trips as
        # distinct from None (Part 3 §3 n.7).
        constraints = frame.dynamics.constraints
        mask_by_atom: list[list[bool]] | None = None
        if constraints is not None:
            out.append("Selective dynamics")
            if constraints:
                # Exactly one selective_dynamics constraint carrying a per-atom mask.
                raw = constraints[0].parameters.get("mask", [])
                mask_by_atom = [list(m) for m in raw]
            else:
                mask_by_atom = [[True, True, True] for _ in atoms.symbols]

        out.append("Cartesian")
        for atom_idx in permutation:
            pos = atoms.positions[atom_idx]
            line = f"  {_fmt(pos[0])} {_fmt(pos[1])} {_fmt(pos[2])}"
            if mask_by_atom is not None:
                flags = mask_by_atom[atom_idx]
                line += " " + " ".join("T" if f else "F" for f in flags)
            out.append(line)

        velocities = frame.dynamics.velocities
        if velocities is not None:
            out.append("")  # blank separator before the velocity block
            out.append("Cartesian")
            for atom_idx in permutation:
                v = velocities[atom_idx]
                out.append(f"  {_fmt(v[0])} {_fmt(v[1])} {_fmt(v[2])}")

        predictor = canonical.user_metadata.custom_global.get(_PREDICTOR_KEY)
        if isinstance(predictor, str) and predictor:
            out.append("")
            out.append(predictor)

        stream.write(("\n".join(out) + "\n").encode("utf-8"))

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        none = FieldCapability(level=CapabilityLevel.NONE)
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "cell.lattice_vectors": full,
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only fully periodic (T,T,T); other PBC combinations cannot be "
                    "represented.",
                ),
                "cell.space_group": none,
                "dynamics.velocities": full,
                "dynamics.forces": none,
                "dynamics.constraints": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only per-axis fixed-atom masks (selective dynamics).",
                ),
                "electronic.total_energy": none,
                "electronic.stress": none,
                "electronic.charges": none,
                "electronic.magnetic_moments": none,
                "simulation.*": none,
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only the POSCAR title (poscar:comment) and CONTCAR predictor-corrector "
                    "block (contcar:predictor_corrector); other custom_global keys are dropped.",
                ),
                "user_metadata.custom_per_atom": none,
                "user_metadata.custom_per_frame": none,
            },
            max_frames=1,
            required_fields=["atoms.symbols", "atoms.positions", "cell.lattice_vectors"],
            native_coordinate_system="both",
            lossy_notes=[
                "Positions written with full float64 precision; sub-ulp differences possible "
                "on round-trip through fixed-width VASP readers."
            ],
        )


def make_poscar_exporter() -> PoscarExporter:
    return PoscarExporter(format_id="poscar")


def make_contcar_exporter() -> PoscarExporter:
    return PoscarExporter(format_id="contcar")
