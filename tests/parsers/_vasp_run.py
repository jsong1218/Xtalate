"""A shared synthetic VASP run for the OUTCAR↔vasprun cross-check (v1.2 M43-S1; standing rule 4).

One run — the same atoms, per-step energies/forces/stress/positions/cells — authored as **both** an
OUTCAR (VASP 6.x layout) and a vasprun.xml (classical layout), so the two readers must agree. The
run
is the single source of physical truth; each renderer spells it in its own format's conventions and
the two parsers map back to the same canonical values (the whole point of standing rule 4). S2
extends this module with a VASP 5.x OUTCAR rendering of the same run.

The canonical quantities are chosen hand-verifiable:

* positions are Cartesian (Å) against a fixed 10 Å cubic cell; the OUTCAR spelling writes them
  as-is while the vasprun.xml spelling writes them **direct** (fractional) — the positions-mode
  trap.
* ``stress`` is canonical tension-positive eV/Å³; both spellings convert it to VASP's
  compression-positive kBar (negate × ``K_BAR_PER_EV_A3``) — the OUTCAR ``in kB`` line as a VASP
  Voigt-6 and the vasprun.xml ``<varray name="stress">`` as a 3×3 — the sign trap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xtalate.parsers._vasp import K_BAR_PER_EV_A3
from xtalate.schema.elements import SYMBOL_TO_Z

_K = K_BAR_PER_EV_A3


@dataclass(frozen=True)
class Step:
    energy: float
    forces: list[list[float]]
    stress: list[list[float]] | None  # canonical tension-positive eV/Å³ (symmetric 3×3)
    positions: list[list[float]]  # Cartesian Å
    lattice: list[list[float]]  # rows a, b, c (Å)


@dataclass(frozen=True)
class Run:
    program: str
    species: list[tuple[str, int]]  # [(symbol, count), ...] in declared order
    steps: list[Step]

    @property
    def symbols(self) -> list[str]:
        out: list[str] = []
        for symbol, count in self.species:
            out.extend([symbol] * count)
        return out


def _kbar(canonical: list[list[float]]) -> list[list[float]]:
    """The compression-positive kBar 3×3 for a canonical tension-positive tensor (negate × K)."""
    return [[-value * _K for value in row] for row in canonical]


def _voigt6_kbar(canonical: list[list[float]]) -> list[float]:
    """The VASP-ordered Voigt-6 [XX, YY, ZZ, XY, YZ, ZX] compression-positive kBar for a tensor."""
    s = canonical
    return [
        -s[0][0] * _K,
        -s[1][1] * _K,
        -s[2][2] * _K,
        -s[0][1] * _K,
        -s[1][2] * _K,
        -s[0][2] * _K,
    ]


def _direct(positions: list[list[float]], lattice: list[list[float]]) -> list[list[float]]:
    """Direct (fractional) coordinates: Cartesian rows @ inverse(lattice)."""
    result = np.asarray(positions, dtype=float) @ np.linalg.inv(np.asarray(lattice, dtype=float))
    return [[float(v) for v in row] for row in result]


def render_outcar(run: Run, *, layout: str = "6x") -> str:
    """The run as a VASP OUTCAR log (Cartesian positions, 'in kB' Voigt-6 stress).

    ``layout`` is ``"6x"`` (the VASP 6.3.2 spelling, S1) or ``"5x"`` (the VASP 5.4.4 spelling, S2):
    the **same** run re-spelled with the documented 5.x↔6.x whitespace/column/label drift — narrower
    7-decimal fixed columns, a scientific-notation ``in kB`` line, a tightened energy line, and the
    5.x-era banner/POTCAR wording. The two spellings must map back to the same canonical values (the
    S2 go/no-go gate), so both are fed to the OUTCAR reader and asserted against vasprun.xml.
    """
    v5 = layout == "5x"
    lines: list[str] = [
        (
            " vasp.5.4.4 18May18 (build May 18 2018 12:00:00) complex"
            if v5
            else f" {run.program} 08Feb23 (build Aug 08 2023 12:00:00) complex"
        ),
        "",
    ]
    for symbol, _count in run.species:
        lines.append(f"  POTCAR:    PAW_PBE {symbol} " + ("08Apr2002" if v5 else "15Jun2001"))
        lines.append(f"    VRHFIN ={symbol}: " + ("s" if v5 else "1s1"))
    lines.append("")
    lines.append(
        "  ions per type =   2  1"
        if v5
        else "  ions per type =               " + "   ".join(str(c) for _s, c in run.species)
    )
    lines.append("")
    lines.append(f"  NIONS =   {len(run.symbols)}" if v5 else f"  NIONS =       {len(run.symbols)}")
    lines.append("")
    _lattice_block(lines, run.steps[0].lattice, v5=v5)
    for n, step in enumerate(run.steps, start=1):
        lines.append(f"{f' Iteration {n}({n}) ':-^80}")
        lines.append("")
        # Real VASP intra-step order: stress and (NpT) the step's own cell precede the
        # POSITION/TOTAL-FORCE table; the energy(sigma->0) summary follows it.
        if step.stress is not None:
            voigt = _voigt6_kbar(step.stress)
            lines.append("  FORCE on cell =-STRESS in cart. coord.  units (eV):")
            if v5:
                lines.append("    in kB   " + "   ".join(f"{v:.10E}" for v in voigt))
            else:
                lines.append("    in kB         " + " ".join(f"{v:.10f}" for v in voigt))
            lines.append("")
        if step.lattice != run.steps[0].lattice:
            _lattice_block(lines, step.lattice, v5=v5)
        lines.append(
            "  -----------------------------------------------------------------------------"
        )
        lines.append("    POSITION                                       TOTAL-FORCE (eV/Angst)")
        lines.append(
            "  -----------------------------------------------------------------------------"
        )
        for (x, y, z), (fx, fy, fz) in zip(step.positions, step.forces, strict=True):
            if v5:
                lines.append(f"    {x: .7f}  {y: .7f}  {z: .7f}  {fx: .7f}  {fy: .7f}  {fz: .7f}")
            else:
                lines.append(f"      {x:.8f}   {y:.8f}   {z:.8f}   {fx:.8f}  {fy:.8f}  {fz:.8f}")
        lines.append(
            "  -----------------------------------------------------------------------------"
        )
        lines.append(
            "     total drift:                                0.00000000   0.00000000   0.00000000"
        )
        lines.append("")
        lines.append("  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)")
        if v5:
            lines.append(
                f"    energy without entropy= {step.energy:.8f} "
                f"energy(sigma->0) = {step.energy:.8f}"
            )
        else:
            lines.append(
                f"    energy  without entropy=       {step.energy:.8f}"
                f"  energy(sigma->0) =       {step.energy:.8f}"
            )
        lines.append("")
    return "\n".join(lines)


def _lattice_block(lines: list[str], lattice: list[list[float]], *, v5: bool = False) -> None:
    lines.append("  direct lattice vectors                 reciprocal lattice vectors")
    inv = np.linalg.inv(np.asarray(lattice))
    for row, rec_row in zip(lattice, inv.T, strict=True):
        if v5:
            lines.append(
                f"    {row[0]: .7f}  {row[1]: .7f}  {row[2]: .7f}  "
                f"{rec_row[0]: .7f}  {rec_row[1]: .7f}  {rec_row[2]: .7f}"
            )
        else:
            lines.append(
                f"     {row[0]:.10f}  {row[1]:.10f}  {row[2]:.10f}     "
                f"{rec_row[0]:.10f}  {rec_row[1]:.10f}  {rec_row[2]:.10f}"
            )
    lines.append("")


def render_vasprun(run: Run) -> str:
    """The run as a classical vasprun.xml (direct positions, 3×3 kBar stress varray)."""
    symbols = run.symbols
    species_index = {}
    n = 1
    for symbol, _count in run.species:
        species_index[symbol] = n
        n += 1
    parts: list[str] = [
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n<vasprun>\n',
        "<generator>\n",
        f'  <i name="program" type="string" >{run.program}</i>\n',
        "</generator>\n",
        "<atominfo>\n",
        '  <array name="atomtypes">\n',
        "    <dimension>2</dimension>\n",
        "    <field> mass </field>\n    <field> Z </field>\n    <field> psp </field>\n",
    ]
    for symbol, _count in run.species:
        atomic_num = SYMBOL_TO_Z[symbol]
        parts.append(f"    <v> 1.0 {atomic_num}.0 8 </v>\n")
    parts.append("  </array>\n")
    parts.append('  <array name="atoms">\n')
    parts.append("    <dimension>3</dimension>\n")
    parts.append(
        "    <field> vasp_x </field>\n    <field> vasp_y </field>\n    <field> vasp_z </field>\n"
        "    <field> atom_type </field>\n"
    )
    first_direct = _direct(run.steps[0].positions, run.steps[0].lattice)
    parts.append("    <set>\n")
    for sym, (x, y, z) in zip(symbols, first_direct, strict=True):
        parts.append(f"      <c> {x:.8f} {y:.8f} {z:.8f} {species_index[sym]} </c>\n")
    parts.append("    </set>\n  </array>\n</atominfo>\n")
    parts.append('<structure name="initialpos" >\n')
    _xml_structure(parts, run.steps[0].lattice, first_direct)
    parts.append("</structure>\n")
    for step in run.steps:
        parts.append("<calculation>\n")
        parts.append("  <energy>\n")
        parts.append(f'    <i name="e_0_energy" type="float" > {step.energy} </i>\n')
        parts.append("  </energy>\n")
        parts.append('  <varray name="forces" >\n')
        for fx, fy, fz in step.forces:
            parts.append(f"    <v> {fx} {fy} {fz} </v>\n")
        parts.append("  </varray>\n")
        if step.stress is not None:
            parts.append('  <varray name="stress" >\n')
            for row in _kbar(step.stress):
                parts.append("    <v> " + " ".join(repr(v) for v in row) + " </v>\n")
            parts.append("  </varray>\n")
        direct = _direct(step.positions, step.lattice)
        parts.append("  <structure>\n")
        _xml_structure(parts, step.lattice, direct)
        parts.append("  </structure>\n")
        parts.append("</calculation>\n")
    parts.append("</vasprun>\n")
    return "".join(parts)


def _xml_structure(parts: list[str], lattice: list[list[float]], direct: list[list[float]]) -> None:
    parts.append('  <crystal>\n    <varray name="basis" >\n')
    for row in lattice:
        parts.append("      <v> " + " ".join(repr(v) for v in row) + " </v>\n")
    parts.append("    </varray>\n  </crystal>\n")
    parts.append('  <varray name="positions" >\n')
    for x, y, z in direct:
        parts.append(f"    <v> {x!r} {y!r} {z!r} </v>\n")
    parts.append("  </varray>\n")


#: The one shared run the cross-check reads (H2O, 3 steps, fixed 10 Å cell; stress on steps 0 and 2,
#: absent on step 1 so the two readers must agree stress is None there too).
H2O_RUN = Run(
    program="vasp.6.3.2",
    species=[("H", 2), ("O", 1)],
    steps=[
        Step(
            energy=-76.4,
            forces=[[0.2, -0.1, 0.0], [-0.1, 0.05, 0.0], [-0.1, 0.0, 0.05]],
            stress=[[-1.0, -0.25, -0.0625], [-0.25, -2.0, -0.125], [-0.0625, -0.125, -0.5]],
            positions=[[5.0, 7.5, 5.0], [7.5, 5.0, 5.0], [5.0, 5.0, 5.0]],
            lattice=[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],
        ),
        Step(
            energy=-76.41,
            forces=[[0.1, -0.05, 0.0], [-0.05, 0.02, 0.0], [-0.05, 0.0, 0.02]],
            stress=None,
            positions=[[5.0, 7.3, 5.0], [7.3, 5.0, 5.0], [5.0, 5.0, 5.0]],
            lattice=[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],
        ),
        Step(
            energy=-76.42,
            forces=[[0.01, -0.01, 0.0], [-0.01, 0.005, 0.0], [-0.01, 0.0, 0.005]],
            stress=[[-1.0, -0.25, -0.0625], [-0.25, -2.0, -0.125], [-0.0625, -0.125, -0.5]],
            positions=[[5.0, 7.4, 5.0], [7.4, 5.0, 5.0], [5.0, 5.0, 5.0]],
            lattice=[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],
        ),
    ],
)
