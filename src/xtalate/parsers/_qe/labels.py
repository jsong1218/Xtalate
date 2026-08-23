"""Shared QE *output* label-extraction mappings (v1.4 M52-S1; DECISIONS.md D195).

Pure functions from *parsed pw.x output values* → canonical fields, with **no log-line or
tokenizing knowledge** — so the pw.x output reader (``qe_pw_out.py``) does the log scraping
and hands this module the parsed numbers, exactly as ``parsers._vasp.labels`` serves the
VASP readers (D160). The M50 ``_qe`` core holds QE's *structural* (input) mappings — ``ibrav``
expansion, per-card unit conversion, ``BOHR_TO_ANGSTROM`` — and this module adds the *output*
label mappings the M52 trap calls for, each hand-pinned by a fixture and D-numbered:

* **energy: Ry → eV** — the ``!    total energy`` value, in Rydberg.
* **forces: Ry/bohr → eV/Å** — the ``Forces acting on atoms`` block.
* **stress: Ry/bohr³ → tension-positive eV/Å³** — the ``total   stress`` 3×3 tensor.

**The stress-sourcing decision (D195).** Stress is computed from QE's native **Ry/bohr³**
block using QE's own constants (``BOHR_TO_ANGSTROM`` = ``bohr_radius_angs``, already in the
``_qe`` core — reused, never forked — and ``RY_TO_EV`` = QE's ``RYTOEV``), and QE's **kbar**
column is used as a *within-file* cross-check. **``_vasp`` is never imported**: coupling the
two format cores across the import boundary would let VASP's sign/unit facts leak into a QE
read (D195 rejected alternative (a)); the universal kBar→eV/Å³ constant is *stated* here, not
borrowed.

**The stress sign (verified, not assumed).** QE prints its ``total   stress`` tensor
**compression-positive** — the ASE reference reader (``ase.io.espresso._get_stress``)
states it in code: *"sign convention is opposite of ase"* (ASE's convention is
tension-positive, the canonical one). So the mapping is a deterministic sign flip to
tension-positive eV/Å³, recorded in ``parse_notes`` — never a silent guess, and the exact
hazard the plan's trap names (a stress sign that silently flips between the QE input/output
and the canonical convention poisons a training set).

**Forces need no sign flip.** QE's ``Forces acting on atoms`` are the forces *acting on* the
atoms (``-dE/dr``), the same convention as VASP's ``TOTAL-FORCE`` column, so the mapping is
a pure unit conversion.

This module imports only ``xtalate.schema``-adjacent helpers (numpy) plus the ``_qe``
structural core's ``BOHR_TO_ANGSTROM`` — never a reader, never another format core (P2).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

import numpy as np

from xtalate.parsers._qe import BOHR_TO_ANGSTROM

#: A reader may hand lists or ndarrays; both are "parsed pw.x output values".
_RowSeq: TypeAlias = Sequence[Sequence[float]] | np.ndarray

#: QE's own Rydberg → eV factor, ``Modules/constants.f90`` ``RYTOEV = 13.605693122994_dp``
#: (= ``AUTOEV/2``). Pinned by a hand-computed fixture — a wrong or rounded factor would be a
#: silent scale error at MLIP scale, the same failure class D161 names for VASP's kBar factor
#: (D195). The round-trip stays inside tolerance only because the *same* value QE itself uses
#: is applied here.
RY_TO_EV = 13.605693122994

#: The universal 1 eV/Å³ = 1602.1766208 kBar constant (1 eV = 1.6021766208e-19 J, 1 Å = 1e-10 m,
#: 1 kBar = 1e8 Pa). **Stated, not imported** from ``_vasp.labels`` (where it lives as
#: ``K_BAR_PER_EV_A3``): importing ``_vasp`` from the QE core would couple two format cores
#: across the import boundary, and the constant is a physical fact, not a VASP fact (D195
#: rejected alternative (a)).
_EV_PER_A3_PER_KBAR = 1602.1766208

#: Ry/bohr → eV/Å: QE's ``RYTOEV`` over its ``bohr_radius_angs`` — the exact factor pinned by
#: the hand-computed force fixtures.
FORCES_FACTOR = RY_TO_EV / BOHR_TO_ANGSTROM  # ≈ 25.71103385054424 eV/Å per Ry/bohr

#: Ry/bohr³ → eV/Å³: ``RYTOEV`` over ``bohr_radius_angs`` cubed — the exact factor pinned by
#: the hand-computed stress fixtures.
STRESS_FACTOR = RY_TO_EV / BOHR_TO_ANGSTROM**3  # ≈ 91.8157694288102 eV/Å³ per Ry/bohr³

#: Ry/bohr³ → kBar, for the within-file cross-check of QE's own kbar column against its
#: Ry/bohr³ block (the two must agree after conversion — a disagreement is a structural
#: inconsistency in the file's own two statements of the same tensor).
K_BAR_PER_RY_BOHR3 = STRESS_FACTOR * _EV_PER_A3_PER_KBAR  # ≈ 147105.07919960306 kBar

_PBC_NOTE = (
    "pbc set to (true,true,true): a pw.x output carries no PBC declaration and QE is always "
    "fully periodic (format-defined, not assumed)."
)
_ENERGY_NOTE = (
    "electronic.total_energy read from the '!    total energy' line in Rydberg and converted "
    f"to eV (× {RY_TO_EV}, QE's RYTOEV — Modules/constants.f90)."
)
_FORCES_NOTE = (
    "dynamics.forces read from the 'Forces acting on atoms' block in Ry/bohr and converted to "
    f"eV/Å (× RYTOEV / bohr_radius_angs = × {FORCES_FACTOR}). Forces are the forces acting on "
    "the atoms (-dE/dr), the same convention as VASP's TOTAL-FORCE column, so no sign flip."
)
_STRESS_NOTE = (
    "electronic.stress mapped from the 'total   stress' 3×3 tensor in Ry/bohr³: QE prints "
    "compression-positive (the ASE reference reader confirms 'sign convention is opposite'), "
    f"so the tensor is sign-flipped to canonical tension-positive and converted × {STRESS_FACTOR} "
    "eV/Å³ per Ry/bohr³. The per-row kbar column is cross-checked against the Ry/bohr³ value "
    f"(× {K_BAR_PER_RY_BOHR3} kBar per Ry/bohr³) and the agreement recorded. A step without a "
    "stress block leaves electronic.stress None (P3 — never a defaulted zero tensor)."
)
_SOURCE_CODE_NOTE = "simulation.source_code set to the PWSCF program banner (verbatim)."
_MASSES_NOTE = (
    "Declared atomic-species masses promote to atoms.masses (present-with-value, P3); the "
    "valence and pseudopotential columns of the declared species table are carried verbatim in "
    "user_metadata.custom_global['qe_pw_out:atomic_species'] (label → [valence, mass, "
    "pseudopotential])."
)
_STEP_CELL_NOTE = (
    "Each ionic step's own CELL_PARAMETERS card (when present) supplies that step's cell at its "
    "declared unit; a step without one reuses the running cell (the fixed-cell form)."
)
_STEP_POSITIONS_NOTE = (
    "Each ionic step's own ATOMIC_POSITIONS card (when present) supplies that step's positions "
    "at its declared unit; a step without one reuses the initial configuration."
)
_K_BAR_CROSSCHECK_OK = (
    "the kbar column agrees with the Ry/bohr³ block within tolerance after conversion "
    "(within-file cross-check passed)."
)


def total_energy_from_ry(value: float) -> float:
    """Canonical ``electronic.total_energy`` in eV from QE's Rydberg value."""
    return float(value) * RY_TO_EV


def forces_from_ry_bohr(rows: _RowSeq) -> np.ndarray:
    """Canonical ``dynamics.forces`` in eV/Å from QE's Ry/bohr rows (no sign flip — QE's
    forces are the forces acting on the atoms, the canonical convention)."""
    return np.asarray(rows, dtype=float) * FORCES_FACTOR


def stress_from_qe(tensor_ry_bohr3: _RowSeq) -> np.ndarray:
    """Canonical tension-positive ``electronic.stress`` (eV/Å³, full 3×3) from QE's printed
    Ry/bohr³ tensor.

    QE prints its ``total   stress`` tensor **compression-positive** — the ASE reference
    reader states the sign is "opposite of ase" (ASE = tension-positive, the canonical
    convention) — so the mapping is a deterministic sign flip plus the exact unit factor,
    computed from QE's native block with QE's own constants. The sign is verified, never
    assumed (D195), and recorded in ``parse_notes``.
    """
    return -np.asarray(tensor_ry_bohr3, dtype=float) * STRESS_FACTOR


def kbar_value(ry_bohr3: float) -> float:
    """The kBar equivalent of a Ry/bohr³ value — the within-file cross-check target."""
    return float(ry_bohr3) * K_BAR_PER_RY_BOHR3


def pbc_parse_note() -> str:
    return _PBC_NOTE


def energy_parse_note() -> str:
    return _ENERGY_NOTE


def forces_parse_note() -> str:
    return _FORCES_NOTE


def stress_parse_note() -> str:
    return _STRESS_NOTE


def source_code_parse_note() -> str:
    return _SOURCE_CODE_NOTE


def masses_parse_note() -> str:
    return _MASSES_NOTE


def step_cell_parse_note() -> str:
    return _STEP_CELL_NOTE


def step_positions_parse_note() -> str:
    return _STEP_POSITIONS_NOTE


def kbar_crosscheck_ok_note() -> str:
    return _K_BAR_CROSSCHECK_OK
