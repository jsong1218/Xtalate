"""The Repair Engine — explicit, recorded, user-initiated modification of a Canonical Object
(v1.7 M64).

Repair is "recovery the user initiates", not "recovery a format requires": the decision-card /
``Assumption`` machinery and the report vocabulary are reused wholesale, and every applied repair
records the D249 triple — (a) an ``Assumption`` carrying the operation name and complete
parameters, (b) a plain-language statement of what changed, and (c) a
``ConversionRecord(operation="repair")`` in Provenance — so a conversion stays reproducible from
its report alone (the version's contract: ``P4`` extended from recovery to modification).

The operation set is **closed at four for the whole version** (wrap-into-cell, center,
deduplicate, species reorder — Part 0 §4's "Not a molecular editor" boundary is held by
enumeration). M64 lands **wrap-into-cell** only; M65 lands the remaining three on the same
engine — species reorder first (S1, proving the shared per-atom reindex spine on the safe,
non-destructive operation), then center (S2) and deduplicate (S3). ``identity`` exists solely
as the contract's reference operation (M64-S1 proves the recording spine on it before the hard
operation lands).

Layering (Part 1 §5.1). This package sits below ``conversion`` in the import graph (on the same
row as ``recovery``/``validation``) and depends on ``schema`` + ``sdk`` only; it returns its own
plain result types (``AppliedRepair``, ``RepairOutcome``) that the ``ConversionEngine`` maps onto
the Conversion Report. It never imports ``conversion`` or ``recovery``.
"""

from __future__ import annotations

from xtalate.repair.contract import (
    REPAIR_BLOCK_MISSING_LATTICE,
    SELECTIVE_REDUCTIVE_HAZARD,
    TRANSFORMATIVE_HAZARD,
    AppliedRepair,
    RepairBlock,
    RepairError,
    RepairHazard,
    RepairOperation,
    RepairOutcome,
    RepairRequest,
)
from xtalate.repair.engine import apply_repairs, get_operation
from xtalate.repair.operations import builtin_repair_operations

__all__ = [
    "REPAIR_BLOCK_MISSING_LATTICE",
    "SELECTIVE_REDUCTIVE_HAZARD",
    "TRANSFORMATIVE_HAZARD",
    "AppliedRepair",
    "RepairBlock",
    "RepairError",
    "RepairHazard",
    "RepairOperation",
    "RepairOutcome",
    "RepairRequest",
    "apply_repairs",
    "builtin_repair_operations",
    "get_operation",
]
