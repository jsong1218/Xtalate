"""The concrete repair operations (v1.7 M64).

The operation set is **closed at four for the whole version** — wrap-into-cell (M64), center,
deduplicate, species reorder (M65) — and ``identity``, which is **not** a fifth scientific
operation: it is the reference implementation of the ``RepairOperation`` contract (M64-S1),
used to prove the recording spine and the reproducibility harness before the hard operation
(wrap) lands. ``builtin_repair_operations()`` is the explicit first-party list a higher layer
assembles into a lookup table (the parsers/exporters precedent); third-party repair operations
are a future SDK seam explicitly declined for v1.7 (impl-plan §4 rule 4).
"""

from __future__ import annotations

from typing import Any

from xtalate.repair.contract import RepairOperation
from xtalate.schema import CanonicalObject


class IdentityRepair(RepairOperation):
    """The contract's reference operation (M64-S1): applies no scientific change.

    Exists to prove the recording spine — an ordered, recorded, reproducible repair — before the
    hard operation lands. It records exactly what was requested (including any parameters) and
    states plainly that nothing changed; it is not a fifth scientific operation.
    """

    operation = "identity"

    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        return obj

    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        return (
            "Identity repair (the reference operation): applied for the record — no scientific "
            "value changed."
        )


def builtin_repair_operations() -> list[RepairOperation]:
    """The explicit first-party repair-operation list (M64). Third-party repairs are declined
    for v1.7 (impl-plan §4 rule 4); this list is where an M64-S2 operation registers."""
    return [IdentityRepair()]
