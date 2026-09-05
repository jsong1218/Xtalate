"""Ordered, all-or-nothing application of repair operations (v1.7 M64; D249/D250).

``apply_repairs`` runs a user-specified ordered list of operations against a Canonical Object,
returning the repaired object plus one ``AppliedRepair`` record per application (the D249 triple
source). It never mutates the caller's object and never applies a partial set: a single blocked
operation returns ``canonical=None`` with nothing applied (the recovery-refusal precedent, D22).

Parameters are validated up front to be JSON-serializable (a report must be able to carry the
complete parameters verbatim — reproducibility from the report alone is the version's contract).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from xtalate.repair.contract import (
    AppliedRepair,
    RepairError,
    RepairOperation,
    RepairOutcome,
    RepairRequest,
)
from xtalate.repair.operations import builtin_repair_operations
from xtalate.schema import CanonicalObject


def _operation_table(
    operations: Iterable[RepairOperation],
) -> dict[str, RepairOperation]:
    table: dict[str, RepairOperation] = {}
    for op in operations:
        if not op.operation:
            raise RepairError(f"a repair operation must declare a non-empty name, got {op!r}")
        if op.operation in table:
            raise RepairError(
                f"duplicate repair operation {op.operation!r} — the closed operation set must "
                "not collide"
            )
        table[op.operation] = op
    return table


def get_operation(
    name: str,
    *,
    operations: Iterable[RepairOperation] | None = None,
) -> RepairOperation:
    """Resolve ``name`` to its operation, or raise ``RepairError`` naming the closed set."""
    table = _operation_table(builtin_repair_operations() if operations is None else operations)
    try:
        return table[name]
    except KeyError:
        raise RepairError(
            f"unknown repair operation {name!r}; the closed operation set is {sorted(table)}"
        ) from None


def _validated_parameters(raw: Any, operation: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RepairError(
            f"repair {operation!r} parameters must be a dict, got {type(raw).__name__}"
        )
    parameters = dict(raw)
    try:
        json.dumps(parameters)
    except (TypeError, ValueError) as exc:
        raise RepairError(
            f"repair {operation!r} parameters must be JSON-serializable (the report records "
            f"them verbatim so the repair is reproducible from the report alone): {exc}"
        ) from exc
    return parameters


def apply_repairs(
    source: CanonicalObject,
    requests: Iterable[RepairRequest],
    *,
    operations: Iterable[RepairOperation] | None = None,
) -> RepairOutcome:
    """Apply ``requests`` to ``source`` in order (D250), recording each application.

    All-or-nothing (D249): if any requested operation blocks against the object, the outcome's
    ``canonical`` is ``None``, ``blocked`` names the blocker, and **no** operation has been
    applied to any returned object (the caller's ``source`` is never mutated). On success,
    ``applied`` holds one ``AppliedRepair`` per request, in request order, each with the
    complete recorded parameters and the plain-language statement — the Conversion Engine maps
    these onto the report's ``Assumption`` rows (scenario ``"repair"``), ``warnings``, and the
    provenance ``ConversionRecord(operation="repair")``.
    """
    table = _operation_table(builtin_repair_operations() if operations is None else operations)
    working = source
    applied: list[AppliedRepair] = []
    for request in requests:
        if not isinstance(request, RepairRequest):
            raise RepairError(
                f"repair requests must be RepairRequest objects, got {type(request).__name__}"
            )
        try:
            op = table[request.operation]
        except KeyError:
            raise RepairError(
                f"unknown repair operation {request.operation!r}; the closed operation set is "
                f"{sorted(table)}"
            ) from None
        parameters = _validated_parameters(request.parameters, op.operation)
        block = op.block(working, parameters)
        if block is not None:
            # All-or-nothing: nothing is recorded and nothing is applied — earlier requests in
            # this set only ever touched discarded working copies (the recovery-refusal
            # precedent: a refused resolve records no Assumptions).
            return RepairOutcome(canonical=None, applied=[], blocked=[block])
        result = op.apply(working, parameters)
        applied.append(
            AppliedRepair(
                id="",  # Assigned by the Conversion Engine when it numbers all applied records.
                operation=op.operation,
                # The complete parameters of this application — verbatim request parameters,
                # or the deterministic record an operation computes from the object (D252:
                # species_reorder's permutation map) — the reproducibility harness replays
                # exactly these.
                parameters=op.recorded_parameters(working, parameters),
                description=op.describe(working, parameters),
                # Per-application hazards (D252): an advisory like ATOM_ORDER_CHANGED must
                # not fire when the application changed nothing.
                hazards=op.hazards_for(working, parameters),
            )
        )
        working = result
    return RepairOutcome(canonical=working, applied=applied, blocked=[])
