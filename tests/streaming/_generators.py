"""Deterministic synthetic-trajectory generators for the M12 streaming proof fixture.

The committed generator the memory proof (deliverable 7) stands on: a large multi-frame extXYZ
written straight to a file, frame by frame, from a fixed seed — so the fixture is reproducible bit
for bit and never stored in the repo (Part 8 §4's "generated, never committed" rule, applied early).

The generated trajectory is deliberately *scientific-fields-only* (positions + forces + a per-frame
energy, one fixed cell): no per-frame custom columns, so the streamed and materialized paths are
byte-identical and the memory contrast is dominated by the resident ``Frame``/``Atoms`` objects the
streaming path avoids holding all at once.
"""

from __future__ import annotations

import math
from pathlib import Path

_SYMBOLS = ("Si", "O")


def write_extxyz_trajectory(path: Path, *, n_frames: int, n_atoms: int, seed: int = 1234) -> Path:
    """Write a deterministic ``n_frames × n_atoms`` extXYZ trajectory to ``path``, one frame block
    at a time (never buffering the whole file). Positions drift smoothly per frame so the data is
    non-trivial but fully reproducible from ``(seed, n_frames, n_atoms)``."""
    lattice = "20.0 0.0 0.0 0.0 20.0 0.0 0.0 0.0 20.0"
    with path.open("w", encoding="utf-8") as fh:
        for f in range(n_frames):
            energy = -1.0 * n_atoms + 0.001 * f
            fh.write(f"{n_atoms}\n")
            fh.write(
                f'Lattice="{lattice}" '
                "Properties=species:S:1:pos:R:3:forces:R:3 "
                f'energy={energy:.6f} pbc="T T T"\n'
            )
            for a in range(n_atoms):
                sym = _SYMBOLS[a % len(_SYMBOLS)]
                # A cheap deterministic pseudo-random-ish position/force from (seed, f, a).
                base = (seed * 131 + a * 17 + f * 7) % 1000 / 100.0
                x = (base + 0.01 * f) % 20.0
                y = (base * 1.3 + 0.02 * a) % 20.0
                z = (base * 0.7 + 0.005 * f) % 20.0
                fx = math.sin(base + f * 0.01)
                fy = math.cos(base + a * 0.01)
                fz = math.sin(base * 0.5)
                fh.write(f"{sym} {x:.6f} {y:.6f} {z:.6f} {fx:.6f} {fy:.6f} {fz:.6f}\n")
    return path
