"""Recovery Engine — explicit, never-guessed handling of target-required-but-absent fields.

Implements the three-way hazard model and the fabricative bright line (Part 4 §3):
every applied recovery records an ``Assumption`` (and a ``supplied`` entry when it
fabricates); no default is ever applied silently. The full Part 4 §3.3 catalog of eight
scenarios is registered and hazard-classified (``scenarios.SCENARIO_HAZARD``); v0.2 M7
(Slice 1) resolves ``missing_lattice``, ``frame_selection``, and ``constraint_representation``
preset-only, with the remaining scenarios refusing until their M8 / Slice-2 resolvers land.

Sits below ``conversion`` in the import graph (Part 1 §5.1), so it returns plain result
types (``AppliedAssumption`` etc.) the ``ConversionEngine`` maps onto the Conversion Report;
it never imports ``conversion``.
"""

from __future__ import annotations

from xtalate.recovery.engine import (
    AppliedAssumption,
    FrameDrop,
    PreservedField,
    RecoveryEngine,
    RecoveryError,
    RecoveryResult,
    SuppliedField,
)
from xtalate.recovery.scenarios import (
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
    "PreservedField",
    "RecoveryEngine",
    "RecoveryError",
    "RecoveryResult",
    "SuppliedField",
    "UnresolvedScenario",
    "available_options",
]
