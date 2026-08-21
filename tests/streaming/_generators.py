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

The LAMMPS dump trajectory (M49-S2, D185) is the deployment format's own proof: a generated
10⁴-frame dump — the deployment-trajectory format's ordinary production scale, shared by the
streaming-memory gate and the ``parse_lammpsdump_10k`` / ``convert_lammpsdump_to_extxyz_10k``
benchmark rows. The dump parser is header-eager / snapshot-lazy, so peak memory tracks one
snapshot block; the generator emits the real M46 block spelling (a declared ``ITEM: UNITS``
preamble on the first snapshot, then per-snapshot ``TIMESTEP`` / ``NUMBER OF ATOMS`` /
``BOX BOUNDS`` / ``ATOMS`` blocks), so the fixture is realistic enough that the same bytes could
be benchmarked against real LAMMPS output.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TextIO

import numpy as np

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


def write_vasprun_trajectory(path: Path, *, n_frames: int, n_atoms: int, seed: int = 1234) -> Path:
    """Write a deterministic ``n_frames × n_atoms`` vasprun.xml to ``path``, one ``<calculation>``
    block at a time (never buffering the whole file).

    Emits the **classical** VASP ≤ 6.4 layout the reader accepts (root ``<vasprun>``, an
    ``<atominfo>`` species table, an ``<structure name="initialpos">``, then one ``<calculation>``
    per ionic step) with every label the ``_vasp`` core maps present per frame: ``e_0_energy``,
    ``<varray name="forces">``, and ``<varray name="stress">`` (kBar, compression-positive — the
    file's declared convention, exactly what the reader sign-flips). Positions are direct
    (fractional) against a fixed 20 Å cubic cell; a per-step ``<structure>`` carries each step's
    own (drifting) positions, mirroring the ``relax-h2o`` golden's fixed-cell form. Fully
    reproducible from ``(seed, n_frames, n_atoms)``.

    This is the generator the M44 streaming gate and the ``parse_vasprun_10k`` benchmark share:
    the file is built frame by frame and written straight to disk, so it is never held whole in
    memory (the "generated, never committed" discipline).
    """
    z_by_symbol = {"Si": 14, "O": 8}
    counts = [0, 0]
    for a in range(n_atoms):
        counts[a % 2] += 1

    def _frac(f: int, a: int) -> tuple[float, float, float]:
        base = (seed * 131 + a * 17 + f * 7) % 1000 / 1000.0
        return (
            (base + 0.0001 * f) % 1.0,
            (base * 1.3 + 0.002 * a) % 1.0,
            (base * 0.7 + 0.0005 * f) % 1.0,
        )

    def _basis(cell: float) -> str:
        return (
            f"      <v> {cell:.6f} 0.0 0.0 </v>\n"
            f"      <v> 0.0 {cell:.6f} 0.0 </v>\n"
            f"      <v> 0.0 0.0 {cell:.6f} </v>\n"
        )

    with path.open("w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="ISO-8859-1"?>\n')
        fh.write("<vasprun>\n")
        fh.write("<generator>\n")
        fh.write('  <i name="program" type="string">vasp.6.1.2</i>\n')
        fh.write('  <i name="version" type="string">6.1.2</i>\n')
        fh.write(
            '  <i name="subversion" type="string">16Mar2019 (build Mar'
            " 16 2019) complex parallel</i>\n"
        )
        fh.write('  <i name="platform" type="string">LinuxGNU</i>\n')
        fh.write("</generator>\n")
        fh.write("<incar>\n")
        fh.write(
            '  <i type="string" name="SYSTEM">synthetic vasprun'
            " trajectory, generated never committed</i>\n"
        )
        fh.write("</incar>\n")
        fh.write("<atominfo>\n")
        fh.write('  <array name="atomtypes">\n')
        fh.write("    <dimension>2</dimension>\n")
        fh.write("    <field> mass </field>\n")
        fh.write("    <field> Z </field>\n")
        fh.write("    <field> psp </field>\n")
        for sym in _SYMBOLS:
            fh.write(f"    <v> {z_by_symbol[sym]:.3f} {z_by_symbol[sym]}.0 8 </v>\n")
        fh.write("    <set>\n")
        fh.write("      <rcmax> 3.0 </rcmax>\n")
        fh.write("    </set>\n")
        fh.write("  </array>\n")
        fh.write('  <array name="atoms">\n')
        fh.write("    <dimension>2</dimension>\n")
        fh.write("    <field> vasp_x </field>\n")
        fh.write("    <field> vasp_y </field>\n")
        fh.write("    <field> vasp_z </field>\n")
        fh.write("    <field> atom_type </field>\n")
        fh.write("    <set>\n")
        fh.write("      <rcmax> 3.0 </rcmax>\n")
        for a in range(n_atoms):
            x, y, z = _frac(0, a)
            fh.write(f"      <c> {x:.6f} {y:.6f} {z:.6f} {a % 2 + 1} </c>\n")
        fh.write("    </set>\n")
        fh.write("  </array>\n")
        fh.write("</atominfo>\n")
        fh.write('<structure name="initialpos" >\n')
        fh.write("  <crystal>\n")
        fh.write('    <varray name="basis" >\n')
        fh.write(_basis(20.0))
        fh.write("    </varray>\n")
        fh.write('    <i name="volume"> 8000.0 </i>\n')
        fh.write('    <i name="energy"> 0.0 </i>\n')
        fh.write("  </crystal>\n")
        fh.write('  <varray name="positions" mode="direct" >\n')
        for a in range(n_atoms):
            x, y, z = _frac(0, a)
            fh.write(f"    <v> {x:.6f} {y:.6f} {z:.6f} </v>\n")
        fh.write("  </varray>\n")
        fh.write("</structure>\n")
        for f in range(n_frames):
            energy = -1.0 * n_atoms + 0.001 * f
            fh.write("<calculation>\n")
            fh.write("  <energy>\n")
            fh.write(f'    <i name="e_0_energy" type="float"> {energy:.6f} </i>\n')
            fh.write(f'    <i name="e_fr_energy" type="float"> {energy + 0.001:.6f} </i>\n')
            fh.write(f'    <i name="e_wo_entrp" type="float"> {energy:.6f} </i>\n')
            fh.write("  </energy>\n")
            fh.write('  <varray name="forces" >\n')
            for a in range(n_atoms):
                base = (seed * 131 + a * 17 + f * 7) % 1000 / 100.0
                fx = math.sin(base + f * 0.01)
                fy = math.cos(base + a * 0.01)
                fz = math.sin(base * 0.5)
                fh.write(f"    <v> {fx:.6f} {fy:.6f} {fz:.6f} </v>\n")
            fh.write("  </varray>\n")
            sxx = 1602.1766208 + 0.001 * f
            syy = 3204.3532416 + 0.001 * f
            szz = 801.0883104 + 0.001 * f
            sxy = 400.5441552 + 0.001 * f
            fh.write('  <varray name="stress" >\n')
            fh.write(f"    <v> {sxx:.6f} {sxy:.6f} 0.0 </v>\n")
            fh.write(f"    <v> {sxy:.6f} {syy:.6f} 0.0 </v>\n")
            fh.write(f"    <v> 0.0 0.0 {szz:.6f} </v>\n")
            fh.write("  </varray>\n")
            fh.write("  <structure>\n")
            fh.write("    <crystal>\n")
            fh.write('      <varray name="basis" >\n')
            fh.write(_basis(20.0))
            fh.write("      </varray>\n")
            fh.write('      <i name="volume"> 8000.0 </i>\n')
            fh.write('      <i name="energy"> 0.0 </i>\n')
            fh.write("    </crystal>\n")
            fh.write('    <varray name="positions" mode="direct" >\n')
            for a in range(n_atoms):
                x, y, z = _frac(f, a)
                fh.write(f"      <v> {x:.6f} {y:.6f} {z:.6f} </v>\n")
            fh.write("    </varray>\n")
            fh.write("  </structure>\n")
            fh.write("</calculation>\n")
        fh.write("</vasprun>\n")
    return path


def write_outcar_trajectory(path: Path, *, n_frames: int, n_atoms: int, seed: int = 1234) -> Path:
    """Write a deterministic ``n_frames × n_atoms`` OUTCAR to ``path``, one ionic step at a time
    (never buffering the whole file).

    Emits the **real VASP intra-step order** the reader keys on (D167): per step, the ``in kB``
    stress line precedes the ``POSITION … TOTAL-FORCE`` table, and the ``FREE ENERGIE`` summary
    carrying ``energy(sigma->0)`` follows it — forces are computed and printed first, the
    electronic-energy summary last. Every label the ``_vasp`` core maps is present per frame
    (Cartesian positions + forces from the table, ``energy(sigma->0)``, the ``in kB`` Voigt-6
    stress), against a fixed 20 Å cubic cell. Fully reproducible from
    ``(seed, n_frames, n_atoms)``.

    This is the generator the M44 streaming gate and the ``parse_outcar_10k`` /
    ``convert_outcar_to_extxyz_10k`` benchmarks share, mirroring the ``relax-h2o`` golden's real
    byte layout rather than hand-inventing one.
    """
    counts = [0, 0]
    for a in range(n_atoms):
        counts[a % 2] += 1
    with path.open("w", encoding="utf-8") as fh:
        fh.write(" vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex\n\n")
        for sym in _SYMBOLS:
            fh.write(f"  POTCAR:    PAW_PBE {sym} 15Jun2001\n")
            fh.write(f"    VRHFIN ={sym}:\n")
            fh.write(f"    TITEL  = PAW_PBE {sym} 15Jun2001\n")
        fh.write("\n")
        fh.write(f"  ions per type =      {counts[0]:>11} {counts[1]:>4}\n")
        fh.write("\n")
        fh.write(f"  NIONS =       {n_atoms}\n")
        fh.write("\n")
        fh.write("  direct lattice vectors                 reciprocal lattice vectors\n")
        fh.write(
            "     20.000000000  0.000000000  0.000000000    "
            " 0.050000000  0.000000000  0.000000000\n"
        )
        fh.write(
            "      0.000000000 20.000000000  0.000000000    "
            " 0.000000000  0.050000000  0.000000000\n"
        )
        fh.write(
            "      0.000000000  0.000000000 20.000000000    "
            " 0.000000000  0.000000000  0.050000000\n"
        )
        fh.write("\n")
        for f in range(n_frames):
            energy = -1.0 * n_atoms + 0.001 * f
            fh.write(
                f" ----------------------------------- Iteration"
                f" {f + 1:>4}({f + 1:>4})  ---------------------------------------\n\n"
            )
            fh.write("  FORCE on cell =-STRESS in cart. coord.  units (eV):\n")
            fh.write(
                "  Direction     XX          YY          ZZ          XY          YZ          ZX\n"
            )
            fh.write(
                "  ---------------------------------------------------------------------------\n"
            )
            fh.write("    Alpha Z       0.00        0.00        0.00\n")
            fh.write(
                "    Ewald        -500.00     -500.00     -500.00      0.00"
                "        0.00        0.00\n"
            )
            fh.write(
                "  ---------------------------------------------------------------------------\n"
            )
            fh.write(
                "    Total         500.00      500.00      500.00      0.00"
                "        0.00        0.00\n"
            )
            sxx = 1602.1766208 + 0.001 * f
            syy = 3204.3532416 + 0.001 * f
            szz = 801.0883104 + 0.001 * f
            sxy = 400.5441552 + 0.001 * f
            syz = 200.2720776 + 0.001 * f
            szx = 100.1360388 + 0.001 * f
            fh.write(
                f"    in kB         {sxx:.10f} {syy:.10f} {szz:.10f}"
                f" {sxy:.10f} {syz:.10f} {szx:.10f}\n"
            )
            fh.write("    external pressure =      500.00 kB  Pullay stress =        0.00 kB\n")
            fh.write("\n")
            fh.write(
                "  -----------------------------------------------------------------------------\n"
            )
            fh.write("    POSITION                                       TOTAL-FORCE (eV/Angst)\n")
            fh.write(
                "  -----------------------------------------------------------------------------\n"
            )
            for a in range(n_atoms):
                base = (seed * 131 + a * 17 + f * 7) % 1000 / 100.0
                x = (base + 0.01 * f) % 20.0
                y = (base * 1.3 + 0.02 * a) % 20.0
                z = (base * 0.7 + 0.005 * f) % 20.0
                fx = math.sin(base + f * 0.01)
                fy = math.cos(base + a * 0.01)
                fz = math.sin(base * 0.5)
                fh.write(f"      {x:.8f}   {y:.8f}   {z:.8f}   {fx:.8f}  {fy:.8f}  {fz:.8f}\n")
            fh.write(
                "  -----------------------------------------------------------------------------\n"
            )
            fh.write(
                "     total drift:                               "
                " 0.00000000   0.00000000   0.00000000\n"
            )
            fh.write("\n")
            fh.write("  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)\n")
            fh.write("  -------------------------------------------------------------------\n")
            fh.write(f"    free  energy   TOTEN  =       {energy + 0.001:.8f} eV\n")
            fh.write("\n")
            fh.write(
                f"    energy  without entropy=       {energy:.8f} "
                f" energy(sigma->0) =       {energy:.8f}\n"
            )
            fh.write("\n")
    return path


def write_lammps_dump_trajectory(
    path: Path, *, n_frames: int, n_atoms: int, seed: int = 1234
) -> Path:
    """Write a deterministic ``n_frames × n_atoms`` LAMMPS dump to ``path``, one snapshot block
    at a time (never buffering the whole file).

    Emits the M46 block spelling the parser keys on: a declared ``ITEM: UNITS metal`` preamble
    on the **first** snapshot only (so no recovery preset is ever needed — the declared-vs-
    ambiguous contrast), then per snapshot ``ITEM: TIMESTEP`` / ``NUMBER OF ATOMS`` /
    ``BOX BOUNDS pp pp pp`` / ``ATOMS id element x y z``, element-labeled atoms against a fixed
    20 Å cubic cell whose positions drift smoothly per frame. Atoms are written in ascending id
    order, so the id-sort is a no-op and the parse stays warning-free. Fully reproducible from
    ``(seed, n_frames, n_atoms)``.

    This is the generator the M49-S2 streaming gate (``tests/streaming/test_streaming_memory.py``)
    and the ``parse_lammpsdump_10k`` / ``convert_lammpsdump_to_extxyz_10k`` benchmarks share: the
    dump is built frame by frame and written straight to disk, so it is never held whole in memory
    (the "generated, never committed" discipline, Part 8 §4).
    """
    with path.open("w", encoding="utf-8") as fh:
        for f in range(n_frames):
            if f == 0:
                # LAMMPS writes the unit-style preamble on the first snapshot only (dump.cpp
                # write_header); later snapshots inherit it.
                fh.write("ITEM: UNITS\nmetal\n")
            fh.write("ITEM: TIMESTEP\n")
            fh.write(f"{f}\n")
            fh.write("ITEM: NUMBER OF ATOMS\n")
            fh.write(f"{n_atoms}\n")
            fh.write("ITEM: BOX BOUNDS pp pp pp\n")
            fh.write("0 20\n0 20\n0 20\n")
            fh.write("ITEM: ATOMS id element x y z\n")
            for a in range(n_atoms):
                sym = _SYMBOLS[a % len(_SYMBOLS)]
                base = (seed * 131 + a * 17 + f * 7) % 1000 / 100.0
                x = (base + 0.01 * f) % 20.0
                y = (base * 1.3 + 0.02 * a) % 20.0
                z = (base * 0.7 + 0.005 * f) % 20.0
                fh.write(f"{a + 1} {sym} {x:.6f} {y:.6f} {z:.6f}\n")
    return path


def write_ase_traj_trajectory(path: Path, *, n_frames: int, n_atoms: int, seed: int = 1234) -> Path:
    """Write a deterministic ``n_frames × n_atoms`` ASE ``.traj`` to ``path``, one image at a time.

    ASE's ``TrajectoryWriter`` appends each image to the ULM container as it is handed over, so the
    file is built frame by frame without ever holding the whole trajectory in memory — the same
    "generated, never committed" discipline as the extXYZ/XDATCAR seeds, and the write side of the
    M14E streaming-memory proof (the read side is what the test actually measures).

    Each frame carries positions + ``forces`` + a per-frame ``energy`` inside a real 20 Å cubic
    cell (``pbc=True``), so it converts cleanly to extXYZ with no recovery and the streamed and
    materialized paths are byte-identical. Positions/forces drift smoothly per frame, so the data is
    non-trivial but fully reproducible from ``(seed, n_frames, n_atoms)``.
    """
    # Import ASE lazily: the streaming seeds are import-light by default, and only this generator
    # needs the scientific stack (mirrors how the test module drives the ASE-backed parser).
    from ase import Atoms
    from ase.calculators.singlepoint import SinglePointCalculator
    from ase.io.trajectory import TrajectoryWriter

    symbols = [_SYMBOLS[a % len(_SYMBOLS)] for a in range(n_atoms)]
    writer = TrajectoryWriter(str(path), "w")
    try:
        for f in range(n_frames):
            positions = np.empty((n_atoms, 3), dtype=np.float64)
            forces = np.empty((n_atoms, 3), dtype=np.float64)
            for a in range(n_atoms):
                base = (seed * 131 + a * 17 + f * 7) % 1000 / 100.0
                positions[a] = (
                    (base + 0.01 * f) % 20.0,
                    (base * 1.3 + 0.02 * a) % 20.0,
                    (base * 0.7 + 0.005 * f) % 20.0,
                )
                forces[a] = (
                    math.sin(base + f * 0.01),
                    math.cos(base + a * 0.01),
                    math.sin(base * 0.5),
                )
            atoms = Atoms(symbols=symbols, positions=positions, cell=[20.0, 20.0, 20.0], pbc=True)
            energy = -1.0 * n_atoms + 0.001 * f
            atoms.calc = SinglePointCalculator(atoms, energy=energy, forces=forces)
            writer.write(atoms)
    finally:
        writer.close()
    return path
