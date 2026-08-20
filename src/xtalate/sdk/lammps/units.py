"""Per-style LAMMPS unit tables → canonical Å/fs/eV (M46; the shared `_lammps` core).

The canonical model stores one fixed unit system — Å, fs, eV (Part 2 §3.1) — so a LAMMPS
file's positions, velocities, box bounds, and energies must be converted at parse time,
and the conversion factor depends on the run's declared unit style. Both v1.3 LAMMPS
formats (the dump parser, M46-S2, and the data parser, M48) read these tables; they are
the single hand-verified authority, never re-derived per parser.

**Hand-verification (recorded in DECISIONS.md D174).** Each factor below is checked
against the LAMMPS `units` command documentation (https://docs.lammps.org/units.html,
accessed 2026-08) and the NIST physical constants that page points at ("For all units
except lj, LAMMPS uses physical constants from www.physics.nist.gov"). The per-style
rows the doc states:

* ``metal`` — distance Å, time ps, energy eV, velocity Å/ps.
* ``real`` — distance Å, time fs, energy kcal/mol (the **thermochemical** calorie,
  4.184 J), velocity Å/fs.
* ``si`` — distance m, time s, energy J, velocity m/s.

Each factor is the multiplier that converts one source-style value to the canonical
unit, with the arithmetic shown in the comment beside it. The ``si`` energy factor and
the ``real`` energy factor are the two genuinely non-trivial ones (J→eV and
kcal/mol→eV-per-molecule); the tests cross-check every factor against ``ase.units``
(which embeds the same NIST values) and against hand-worked fixture values.

The option vocabulary (``metal``/``real``/``si``) is the `ambiguous_units` recovery
scenario's choice set (Part 4 §3.3) — the same codes in the same order, and it grows
only by golden-corpus evidence (M49), never from the docs' full style list.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 1 kcal (thermochemical) / 1 mol / 1 eV in J — the exact kcal/mol→eV-per-molecule
#: conversion: 4184 J/mol ÷ (6.02214076e23 molecules/mol × 1.602176634e-19 J/eV).
_REAL_ENERGY_TO_EV = 0.043364104241800934
#: 1 J in eV: 1 / 1.602176634e-19.
_SI_ENERGY_TO_EV = 6.241509074460763e18


@dataclass(frozen=True)
class UnitStyle:
    """One LAMMPS unit style: the conversion factors to the canonical Å/fs/eV system.

    Each ``*_to_*`` factor multiplies a value written in the style's own units to give
    the canonical value (Part 2 §3.1). ``summary`` is the human-readable unit basis,
    stated in reports and parse notes alongside the style code.
    """

    code: str
    distance_to_angstrom: float
    time_to_femtosecond: float
    energy_to_electronvolt: float
    velocity_to_angstrom_per_femtosecond: float
    summary: str


#: The three styles the `ambiguous_units` scenario offers (Part 4 §3.3). Order matches
#: the scenario's option list; breadth grows only by corpus evidence (M49).
UNIT_STYLES: dict[str, UnitStyle] = {
    "metal": UnitStyle(
        code="metal",
        # distance = Å → ×1.
        distance_to_angstrom=1.0,
        # time = ps → ×1e3 (1 ps = 1e3 fs).
        time_to_femtosecond=1e3,
        # energy = eV → ×1.
        energy_to_electronvolt=1.0,
        # velocity = Å/ps = Å / 1e3 fs → ×1e-3.
        velocity_to_angstrom_per_femtosecond=1e-3,
        summary="Å, ps, eV",
    ),
    "real": UnitStyle(
        code="real",
        # distance = Å → ×1.
        distance_to_angstrom=1.0,
        # time = fs → ×1.
        time_to_femtosecond=1.0,
        # energy = kcal/mol (thermochemical 4.184 J) → per-molecule eV (see the module
        # constant): 4184 / (6.02214076e23 × 1.602176634e-19) = 0.0433641 eV.
        energy_to_electronvolt=_REAL_ENERGY_TO_EV,
        # velocity = Å/fs → ×1.
        velocity_to_angstrom_per_femtosecond=1.0,
        summary="Å, fs, kcal/mol",
    ),
    "si": UnitStyle(
        code="si",
        # distance = m → ×1e10 (1 m = 1e10 Å).
        distance_to_angstrom=1e10,
        # time = s → ×1e15 (1 s = 1e15 fs).
        time_to_femtosecond=1e15,
        # energy = J → ×6.241509074e18 (1 J = 1/1.602176634e-19 eV).
        energy_to_electronvolt=_SI_ENERGY_TO_EV,
        # velocity = m/s = 1e10 Å / 1e15 fs → ×1e-5.
        velocity_to_angstrom_per_femtosecond=1e-5,
        summary="m, s, J",
    ),
}


def unit_style(code: str) -> UnitStyle | None:
    """The :class:`UnitStyle` for ``code``, or ``None`` for an unknown style.

    ``None`` (rather than a raise) is the shape the parse-time `ambiguous_units`
    refusal needs: an *unknown* style is not an ambiguity to resolve — it is data the
    catalog cannot interpret, so the parser refuses with its own error rather than
    offering it as a choice (a choice list is the honest option set, Part 4 §3.3).
    """
    return UNIT_STYLES.get(code)
