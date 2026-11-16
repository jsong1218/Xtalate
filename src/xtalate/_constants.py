"""The one home of physical constants (leaf module: imports nothing from xtalate).

Every unit-conversion factor in the parsers and SDK derives from here, so a constant can
never drift between two files. Two values are **pinned to older editions on purpose**
(``BOHR_TO_ANGSTROM_QE``, ``K_BAR_PER_EV_A3``): they are pinned to the values previously used
by the QE and VASP parsers, because hand-computed fixtures and sha256-governed goldens embed
them. The module therefore mixes CODATA editions; each constant below names its edition. The
CODATA-2018 twins are exported for comparison only. Changing a pinned value is an
output-changing act that needs its own decision-log entry.
"""

from __future__ import annotations

# SI 2019 exact definitions
N_A: float = 6.02214076e23  # 1/mol (SI 2019, exact)
E_CHARGE: float = 1.602176634e-19  # C (= J/eV) (SI 2019, exact)
AMU_KG: float = 1.66053906660e-27  # kg (CODATA 2018 value; not exact)

# Hartree in eV (CODATA 2018); the Rydberg is exactly half (QE's RYTOEV is AUTOEV/2).
HARTREE_EV: float = 27.211386245988
RYDBERG_EV: float = HARTREE_EV / 2

# Derived energy/mass factors
KCAL_PER_MOL_EV: float = 4184.0 / (N_A * E_CHARGE)
KJ_PER_MOL_EV: float = 1000.0 / (N_A * E_CHARGE)
J_TO_EV: float = 1.0 / E_CHARGE
KG_TO_AMU: float = 1.0 / AMU_KG

# Pinned (older-edition) values, see module docstring.
# CODATA 2006 Bohr radius; pinned to the QE parser's prior value.
BOHR_TO_ANGSTROM_QE: float = 0.52917720859
# CODATA 2014 e scaled (e * 1e30 / 1e8 with e = 1.6021766208e-19); pinned to the VASP/QE
# parsers' prior value.
K_BAR_PER_EV_A3: float = 1602.1766208

# CODATA 2018 twins (comparison only).
BOHR_TO_ANGSTROM_CODATA2018: float = 0.529177210903
K_BAR_PER_EV_A3_CODATA2018: float = E_CHARGE * 1e30 / 1e8  # 1602.176634
