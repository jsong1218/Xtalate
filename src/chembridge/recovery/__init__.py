"""Recovery Engine — explicit, never-guessed handling of target-required-but-absent fields.

Implements the three-way hazard model and the fabricative bright line (Part 4 §3):
every applied recovery records an ``Assumption`` (and a ``supplied`` entry when it
fabricates); no default is ever applied silently. v0.1 scenarios: ``missing_lattice``
and ``frame_selection`` (preset-only). Implemented in M5.

Sits below ``conversion`` in the import graph (Part 1 §5.1), so it returns plain result
types (``AppliedAssumption`` etc.) the ``ConversionEngine`` maps onto the Conversion Report;
it never imports ``conversion``.
"""

from __future__ import annotations

from chembridge.recovery.engine import (
    AppliedAssumption,
    FrameDrop,
    RecoveryEngine,
    RecoveryError,
    RecoveryResult,
    SuppliedField,
)
from chembridge.recovery.scenarios import (
    SCENARIO_HAZARD,
    HazardClass,
    UnresolvedScenario,
    available_options,
)

__all__ = [
    "SCENARIO_HAZARD",
    "AppliedAssumption",
    "FrameDrop",
    "HazardClass",
    "RecoveryEngine",
    "RecoveryError",
    "RecoveryResult",
    "SuppliedField",
    "UnresolvedScenario",
    "available_options",
]
