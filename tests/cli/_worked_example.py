"""Generator for the spec's flagship worked example: ``relax.traj → POSCAR`` (M14D; Part 4 §5).

The source is the trajectory MASTER_SPEC Part 4 §5 describes verbatim (line 1876): an isolated
**3-atom water molecule** during optimization — **10 frames**, each carrying ``atoms.symbols`` /
``atoms.positions``, ``dynamics.forces``, and ``electronic.total_energy``, with ASE's default zero
cell (which the parser launders to ``cell = None``, Part 3 §2) and **no** velocities, stress,
charges, or constraints. Making that example *executable* is M14's milestone exit door: the emitted
Conversion Report (Part 4 §5, lines 1903–1951) and Validation Report (Part 5 §6, lines 2154–2232)
are diffed against spec-derived fixtures in ``test_worked_example.py``.

Like ``tests/streaming/_generators.py``, this is a committed, deterministic generator — the
``.traj`` bytes are regenerated on demand and never stored in the repo. ASE's ULM writer is
byte-stable (no timestamps, no run-to-run entropy), so the fixture is reproducible bit for bit.
The geometry relaxes smoothly toward a water-like equilibrium and the forces shrink frame to frame,
so the ten frames are genuinely distinct and ``frame_selection=last`` selects a real final
structure — but every number is a closed-form function of the frame index, so the reader can verify
the source by eye rather than trusting a snapshot.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io.trajectory import TrajectoryWriter

# Water in the spec's stated species order (O, H, H) — the order the Conversion Report's
# ``preserved`` detail records ("O, H, H"). Frame 0 is a stretched guess; each frame contracts the
# O–H bonds a little toward equilibrium, so the trajectory reads as a relaxation.
_SYMBOLS = ["O", "H", "H"]
_N_FRAMES = 10


def _frame(index: int) -> Atoms:
    """One water frame: O at the origin, two H atoms whose bonds contract smoothly with ``index``
    and whose forces decay toward zero — a closed-form (seedless, fully reproducible) relaxation."""
    # Bond length eases from 1.10 Å (frame 0) toward ~0.96 Å (the final frame); the HOH geometry
    # stays planar in x–z so every coordinate is a plain function of the frame index.
    bond = 1.10 - 0.014 * index
    positions = np.array(
        [
            [0.0, 0.0, 0.0],
            [bond * np.sin(0.911), 0.0, bond * np.cos(0.911)],
            [-bond * np.sin(0.911), 0.0, bond * np.cos(0.911)],
        ]
    )
    # Forces decay geometrically toward zero as the geometry relaxes; energy descends monotonically.
    forces = np.full((3, 3), 0.5 * 0.6**index)
    forces[0] = 0.0  # the oxygen sits at the origin by construction: no net force on it.
    energy = -14.0 - 0.05 * index
    atoms = Atoms(symbols=_SYMBOLS, positions=positions)  # no cell → ASE default zero cell
    atoms.calc = SinglePointCalculator(atoms, energy=energy, forces=forces)
    return atoms


def write_relax_traj(path: Path) -> Path:
    """Write the deterministic 10-frame water ``relax.traj`` to ``path`` and return it."""
    writer = TrajectoryWriter(str(path), "w")
    for index in range(_N_FRAMES):
        writer.write(_frame(index))
    writer.close()
    return path
