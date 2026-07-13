"""Recovery Engine — explicit, never-guessed handling of target-required-but-absent fields.

Implements the three-way hazard model and the fabricative bright line (Part 4 §3):
every applied recovery records an ``Assumption`` (and a ``supplied`` entry when it
fabricates); no default is ever applied silently. The full Part 4 §3.3 catalog of eight
scenarios is registered and hazard-classified (``scenarios.SCENARIO_HAZARD``). v0.2 M7 resolves
``missing_lattice`` (``manual_input``/``bounding_box``/``upload_reference``), ``frame_selection``
(``first``/``last``/``index``/``split_all``), and ``constraint_representation``
(``project``/``drop_all``) through this engine, and the parse-time scenarios ``missing_species``
and ``truncate_corrupt_tail`` through the parser ``parse_recover`` hook and
``conversion.parse_with_recovery``; ``missing_velocities``/``missing_masses`` refuse until M8, and
``missing_energy`` is optionless.

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
