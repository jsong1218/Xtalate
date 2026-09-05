"""Ordered composition of the closed operation set (v1.7 M65-S3; D254).

The milestone's \"the ordered set works\" evidence: an ordered stack (wrap →
deduplicate → species_reorder) applied through one conversion re-derives
byte-identically from the report's **ordered Assumption chain** alone — the row
order *is* the application order (D250) and each row carries the complete recorded
parameters, so a third party reconstructs the exact stack. A reordered pair
(dedupe → reorder vs reorder → dedupe) demonstrates the order is recorded and
matters: different outputs, and each report's row order names its own stack.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tests.conversion.test_engine import _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.repair import RepairRequest
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame, Provenance


def _stack_source() -> CanonicalObject:
    """A single frame with a cell whose atoms are element-ungrouped and include a
    coincidence the stack resolves: atom 0 at [7, 0, 0] wraps onto atom 2 at [1, 0, 0]
    (one lattice vector apart in a 6 Å cubic cell — minimum-image coincident even before
    wrapping)."""
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(
                    symbols=["Na", "Cl", "Na", "Cl", "Na", "Cl"],
                    positions=np.array(
                        [
                            [7.0, 0.0, 0.0],
                            [2.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [4.0, 0.0, 0.0],
                            [0.0, 2.0, 0.0],
                            [3.0, 3.0, 0.0],
                        ],
                        dtype=float,
                    ),
                ),
                cell=Cell(lattice_vectors=6.0 * np.eye(3), pbc=(True, True, True)),
            )
        ],
        provenance=Provenance(
            source_filename="stack.vasp",
            source_format="poscar",
            original_coordinate_system="cartesian",
        ),
    )


def _convert(
    source: CanonicalObject,
    *,
    reg: Registry | None = None,
    repairs: list[RepairRequest] | None = None,
    **kwargs: Any,
) -> ConversionResult:
    reg = reg or _registry()
    return ConversionEngine(reg).convert(
        source,
        source_format_id="poscar",
        target_format_id="poscar",
        source_filename="stack.vasp",
        repairs=repairs,
        **kwargs,
    )


def _stack() -> list[RepairRequest]:
    return [
        RepairRequest("wrap_into_cell"),
        RepairRequest("deduplicate", {"distance_threshold": 0.5}),
        RepairRequest("species_reorder"),
    ]


def test_ordered_stack_reproduces_from_the_report_chain_alone() -> None:
    reg = _registry()
    source = _stack_source()

    result = _convert(source, reg=reg, repairs=_stack())
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The Assumption chain reconstructs the exact stack, in application order (D250).
    assert [row.choice for row in result.report.repairs] == [
        "wrap_into_cell",
        "deduplicate",
        "species_reorder",
    ]
    # Each row carries the complete recorded parameters (the reproducibility datum). The
    # reorder permutation is in the deduped object's space (5 survivors, symbols
    # [Na, Cl, Cl, Na, Cl]): Na at survivor positions 0 and 3, Cl at 1, 2, 4.
    (wrap_row, dedupe_row, reorder_row) = result.report.repairs
    assert wrap_row.parameters == {}
    assert dedupe_row.parameters["distance_threshold"] == 0.5
    assert dedupe_row.parameters["removed_atoms"] == [{"index": 2, "symbol": "Na"}]
    assert reorder_row.parameters["permutation"] == [0, 3, 1, 2, 4]

    # Re-derive byte-identically by replaying the report's ordered chain verbatim.
    replayed = [RepairRequest(row.choice, dict(row.parameters)) for row in result.report.repairs]
    rederived = _convert(source, reg=reg, repairs=replayed)
    assert rederived.output is not None and rederived.output == result.output
    assert rederived.validation is not None and rederived.validation.status == "passed"

    # The repaired object is what the stack says it is: atom 0 wrapped onto atom 2,
    # atom 2 removed (lowest index survives), then grouped by element.
    assert result.canonical_out.frames[0].atoms.symbols == ["Na", "Na", "Cl", "Cl", "Cl"]


def _order_fixture() -> CanonicalObject:
    """A lone O, plus an {H, O} pair within threshold (0.05 Å). The survivor selection
    genuinely depends on operation order: dedupe-first keeps the pair's lowest index, the
    H at index 1 (removing the O at index 2); reorder-first groups O before H (the lone
    O is the first O), so the pair's O lands at the lower index and dedupe removes the H
    instead — different atoms survive, different output bytes."""
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(
                    symbols=["O", "H", "O"],
                    positions=np.array(
                        [[3.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.05, 0.0, 0.0]], dtype=float
                    ),
                ),
                cell=Cell(lattice_vectors=20.0 * np.eye(3), pbc=(True, True, True)),
            )
        ],
        provenance=Provenance(
            source_filename="order.vasp",
            source_format="poscar",
            original_coordinate_system="cartesian",
        ),
    )


def test_operation_order_is_recorded_and_matters() -> None:
    reg = _registry()
    source = _order_fixture()

    dedupe_first = _convert(
        source,
        reg=reg,
        repairs=[
            RepairRequest("deduplicate", {"distance_threshold": 0.5}),
            RepairRequest("species_reorder"),
        ],
    )
    reorder_first = _convert(
        source,
        reg=reg,
        repairs=[
            RepairRequest("species_reorder"),
            RepairRequest("deduplicate", {"distance_threshold": 0.5}),
        ],
    )

    # Order is recorded: each report's row order names its own stack.
    assert [row.choice for row in dedupe_first.report.repairs] == [
        "deduplicate",
        "species_reorder",
    ]
    assert [row.choice for row in reorder_first.report.repairs] == [
        "species_reorder",
        "deduplicate",
    ]

    # And order matters: dedupe-first keeps the pair's lowest index — the H (removing the
    # O); reorder-first groups the O's first, so the pair's O holds the lower index and the
    # H is removed instead. Different survivors, different output bytes.
    assert dedupe_first.output is not None and reorder_first.output is not None
    assert dedupe_first.output != reorder_first.output
    assert dedupe_first.canonical_out is not None and reorder_first.canonical_out is not None
    assert dedupe_first.canonical_out.frames[0].atoms.symbols == ["O", "H"]
    assert reorder_first.canonical_out.frames[0].atoms.symbols == ["O", "O"]

    # Each order re-derives byte-identically from its own recorded chain.
    for result in (dedupe_first, reorder_first):
        replayed = [
            RepairRequest(row.choice, dict(row.parameters)) for row in result.report.repairs
        ]
        rederived = _convert(source, reg=reg, repairs=replayed)
        assert rederived.output is not None and rederived.output == result.output
        assert rederived.validation is not None and rederived.validation.status == "passed"
