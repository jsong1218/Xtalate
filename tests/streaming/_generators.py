"""Deterministic synthetic-trajectory generators for the M12/M13 streaming proof fixtures.

The committed generators the memory proofs stand on: a large multi-frame trajectory written
straight to a file, frame by frame, from a fixed seed — so each fixture is reproducible bit for
bit and never stored in the repo (Part 8 §4's "generated, never committed" rule, applied early).

The extXYZ trajectory (M12, deliverable 7) is deliberately *scientific-fields-only* (positions +
forces + a per-frame energy, one fixed cell): no per-frame custom columns, so the streamed and
materialized paths are byte-identical and the memory contrast is dominated by the resident
``Frame``/``Atoms`` objects the streaming path avoids holding all at once.

The XDATCAR trajectory (M13) is the *honest* test of the same claim: 10⁴ configurations is an
XDATCAR's ordinary size, not a synthetic stress case, which is why the roadmap put chunking
before this parser rather than after it.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TextIO

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


def write_xdatcar_trajectory(
    path: Path, *, n_frames: int, n_atoms: int, seed: int = 1234, npt: bool = False
) -> Path:
    """Write a deterministic ``n_frames × n_atoms`` XDATCAR to ``path``, one configuration block at
    a time (never buffering the whole file).

    ``npt=False`` writes the fixed-cell form (one header, then back-to-back configurations);
    ``npt=True`` restates the header before every configuration with a slowly expanding cell — the
    memory-hostile form, since every frame then carries its own lattice through the pipeline.

    Positions are Direct (fractional) and drift smoothly per frame, so the data is non-trivial but
    fully reproducible from ``(seed, n_frames, n_atoms, npt)``.
    """
    counts = [0, 0]
    for a in range(n_atoms):
        counts[a % 2] += 1
    species_line = f"   {_SYMBOLS[0]} {_SYMBOLS[1]}\n"
    counts_line = f"   {counts[0]} {counts[1]}\n"
    title = "synthetic XDATCAR (generated, never committed)\n"

    def _header(fh: TextIO, frame: int) -> None:
        a = 20.0 + (0.001 * frame if npt else 0.0)
        fh.write(title)
        fh.write("   1.0\n")
        fh.write(f"     {a:.8f}    0.00000000    0.00000000\n")
        fh.write(f"     0.00000000    {a:.8f}    0.00000000\n")
        fh.write(f"     0.00000000    0.00000000    {a:.8f}\n")
        fh.write(species_line)
        fh.write(counts_line)

    with path.open("w", encoding="utf-8") as fh:
        if not npt:
            _header(fh, 0)
        for f in range(n_frames):
            if npt:
                _header(fh, f)
            fh.write(f"Direct configuration=  {f + 1:>5}\n")
            # XDATCAR groups atoms by element, so emit species 0's atoms then species 1's.
            for species in (0, 1):
                for a in range(species, n_atoms, 2):
                    base = (seed * 131 + a * 17 + f * 7) % 1000 / 1000.0
                    x = (base + 0.0001 * f) % 1.0
                    y = (base * 1.3 + 0.002 * a) % 1.0
                    z = (base * 0.7 + 0.0005 * f) % 1.0
                    fh.write(f"  {x:.8f}  {y:.8f}  {z:.8f}\n")
    return path
