"""deduplicate — the single-structure, no-default, enumerate-what-was-removed
selective-reductive repair (v1.7 M65-S3; D254).

Tests: registration + the shared repair/recovery hazard vocabulary (lockstep with
``HazardClass.SELECTIVE_REDUCTIVE``), the lowest-index-survivor rule with survivor
values kept verbatim (per-atom categories carried through the survivor slice), the
three ``RepairError`` refusals (no threshold, trajectory, removed-atom-under-
constraint), the PBC minimum-image vs plain-Cartesian metric (stated in the record),
the exact {index, symbol} enumeration, the recorded no-op, and the flagship
convert + validate + reproduce-byte-identically harness.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tests.conversion.test_engine import _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.recovery.scenarios import HazardClass
from xtalate.repair import (
    SELECTIVE_REDUCTIVE_HAZARD,
    RepairRequest,
    apply_repairs,
    get_operation,
)
from xtalate.repair.operations import DEDUPE_REMOVED_ATOMS, Deduplicate
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Constraint,
    Dynamics,
    Electronic,
    Frame,
    Provenance,
    UserMetadata,
)


def _provenance(filename: str = "source.vasp") -> Provenance:
    return Provenance(
        source_filename=filename,
        source_format="poscar",
        original_coordinate_system="cartesian",
    )


def _duplicates_object(with_cell: bool = True) -> CanonicalObject:
    """Six atoms with two coincidence clusters — {0, 1, 2} (0.05–0.1 Å apart) and
    {3, 4} (0.05 Å apart) — plus a far lone atom 5. Every per-atom category carries
    distinct values so the survivor-slice tests prove values are kept verbatim."""
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["Na", "Cl", "Na", "Cl", "Na", "Cl"],
            positions=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [0.05, 0.0, 0.0],
                    [0.1, 0.0, 0.0],
                    [3.0, 0.0, 0.0],
                    [3.05, 0.0, 0.0],
                    [6.0, 0.0, 0.0],
                ],
                dtype=float,
            ),
            masses=np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
            occupancies=[1.0, 0.5, 1.0, 0.75, 0.5, 1.0],
        ),
        cell=(
            Cell(lattice_vectors=20.0 * np.eye(3), pbc=(True, True, True)) if with_cell else None
        ),
        dynamics=Dynamics(
            velocities=np.array(
                [
                    [0.1, 0.0, 0.0],
                    [0.0, 0.2, 0.0],
                    [0.0, 0.0, 0.3],
                    [0.4, 0.0, 0.0],
                    [0.0, 0.5, 0.0],
                    [0.0, 0.0, 0.6],
                ],
                dtype=float,
            ),
            forces=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [0.0, 2.0, 0.0],
                    [0.0, 0.0, 3.0],
                    [4.0, 0.0, 0.0],
                    [0.0, 5.0, 0.0],
                    [0.0, 0.0, 6.0],
                ],
                dtype=float,
            ),
        ),
        electronic=Electronic(
            charges=np.array([-1.0, 1.0, -1.0, 1.0, 1.0, -1.0]),
            magnetic_moments=np.array([0.0, 1.0, 0.5, 2.0, 1.5, 0.0]),
        ),
    )
    return CanonicalObject(
        frames=[frame],
        provenance=_provenance(),
        user_metadata=UserMetadata(
            custom_per_atom={
                "tags": np.array([10, 20, 30, 40, 50, 60]),
                "labels": ["a", "b", "c", "d", "e", "f"],
            }
        ),
    )


def _apply(obj: CanonicalObject, parameters: dict[str, Any]) -> tuple[CanonicalObject, Any]:
    outcome = apply_repairs(obj, [RepairRequest("deduplicate", parameters)])
    assert outcome.canonical is not None and not outcome.blocked
    assert [a.operation for a in outcome.applied] == ["deduplicate"]
    return outcome.canonical, outcome.applied[0]


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
        source_filename="source.vasp",
        repairs=repairs,
        **kwargs,
    )


# --- registration + the shared repair/recovery hazard vocabulary ---------------------------


def test_deduplicate_is_registered_and_selective_reductive() -> None:
    op = get_operation("deduplicate")
    assert isinstance(op, Deduplicate)
    assert op.operation == "deduplicate"
    # Dedupe is reductive, not transformative: it draws recovery's own vocabulary, with
    # transformative (D251) the single repair-side addition. Lockstep: the restated
    # constant can never drift from HazardClass.SELECTIVE_REDUCTIVE (repair may not import
    # recovery — layering, D249 — so the value is restated and pinned by this test).
    assert op.hazard_class == SELECTIVE_REDUCTIVE_HAZARD == "selective_reductive"
    assert SELECTIVE_REDUCTIVE_HAZARD == HazardClass.SELECTIVE_REDUCTIVE.value
    assert op.hazards == (DEDUPE_REMOVED_ATOMS,)
    assert DEDUPE_REMOVED_ATOMS.code == "DEDUPE_REMOVED_ATOMS"


# --- survivor rule: lowest index survives, values verbatim (no merging/averaging) ----------


def test_deduplicate_removes_coincident_atoms_lowest_index_survives() -> None:
    source = _duplicates_object()
    repaired, record = _apply(source, {"distance_threshold": 0.5})
    # Clusters {0,1,2} and {3,4}: indices 1, 2 and 4 removed; 0, 3, 5 survive.
    assert repaired.frames[0].atoms.symbols == ["Na", "Cl", "Cl"]
    assert record.parameters["removed_atoms"] == [
        {"index": 1, "symbol": "Cl"},
        {"index": 2, "symbol": "Na"},
        {"index": 4, "symbol": "Na"},
    ]
    assert record.parameters["distance_threshold"] == 0.5


def test_deduplicate_keeps_survivor_values_verbatim() -> None:
    # The survivor of each cluster keeps its OWN values — never an average of the cluster's
    # (that would fabricate positions/values the source never held, P4). Every per-atom
    # category follows the same survivor selection [0, 3, 5].
    source = _duplicates_object()
    repaired, _ = _apply(source, {"distance_threshold": 0.5})
    atoms = repaired.frames[0].atoms

    survivors = [0, 3, 5]
    expected_positions = np.asarray(source.frames[0].atoms.positions)[survivors]
    assert np.array_equal(np.asarray(atoms.positions), expected_positions)
    assert atoms.masses is not None and source.frames[0].atoms.masses is not None
    assert np.array_equal(atoms.masses, source.frames[0].atoms.masses[survivors])
    source_occupancies = source.frames[0].atoms.occupancies
    assert source_occupancies is not None
    assert atoms.occupancies == [source_occupancies[i] for i in survivors]

    dyn = repaired.frames[0].dynamics
    src_dyn = source.frames[0].dynamics
    assert dyn.velocities is not None and src_dyn.velocities is not None
    assert np.array_equal(dyn.velocities, src_dyn.velocities[survivors])
    assert dyn.forces is not None and src_dyn.forces is not None
    assert np.array_equal(dyn.forces, src_dyn.forces[survivors])

    elec = repaired.frames[0].electronic
    src_elec = source.frames[0].electronic
    assert elec.charges is not None and src_elec.charges is not None
    assert np.array_equal(elec.charges, src_elec.charges[survivors])
    assert elec.magnetic_moments is not None and src_elec.magnetic_moments is not None
    assert np.array_equal(elec.magnetic_moments, src_elec.magnetic_moments[survivors])

    tags = repaired.user_metadata.custom_per_atom["tags"]
    labels = repaired.user_metadata.custom_per_atom["labels"]
    assert isinstance(tags, np.ndarray) and isinstance(labels, list)
    assert np.array_equal(tags, np.array([10, 40, 60]))
    assert labels == ["a", "d", "f"]


# --- the three RepairError refusals --------------------------------------------------------


def test_deduplicate_requires_a_positive_threshold() -> None:
    source = _duplicates_object()
    for parameters in (
        {},
        {"distance_threshold": None},
        {"distance_threshold": 0},
        {"distance_threshold": -0.5},
        {"distance_threshold": "near"},
    ):
        try:
            apply_repairs(source, [RepairRequest("deduplicate", parameters)])
        except ValueError as exc:
            message = str(exc)
            assert "distance_threshold" in message
            assert "no default" in message
        else:  # pragma: no cover
            raise AssertionError(f"deduplicate must refuse {parameters!r}")


def test_deduplicate_refuses_a_trajectory() -> None:
    frame = _duplicates_object().frames[0]
    trajectory = CanonicalObject(
        frames=[
            frame,
            frame.model_copy(
                update={
                    "index": 1,
                    "atoms": frame.atoms.model_copy(
                        update={
                            "positions": np.asarray(frame.atoms.positions)
                            + np.array([0.2, 0.0, 0.0])
                        }
                    ),
                }
            ),
        ],
        provenance=_provenance("traj.vasp"),
    )
    try:
        apply_repairs(trajectory, [RepairRequest("deduplicate", {"distance_threshold": 0.5})])
    except ValueError as exc:
        message = str(exc)
        assert "single structure" in message
        assert "2 frames" in message
    else:  # pragma: no cover
        raise AssertionError("a trajectory must refuse deduplicate")


def test_deduplicate_removed_atom_under_constraint_refuses() -> None:
    frame = _duplicates_object().frames[0]
    constrained = frame.model_copy(
        update={
            "dynamics": frame.dynamics.model_copy(
                update={
                    "constraints": [
                        Constraint(kind="fixed_atoms", atom_indices=[1]),  # atom 1 is removed
                        Constraint(kind="fixed_atoms", atom_indices=[5]),  # atom 5 survives
                    ]
                }
            )
        }
    )
    obj = _duplicates_object().model_copy(update={"frames": [constrained]})
    try:
        apply_repairs(obj, [RepairRequest("deduplicate", {"distance_threshold": 0.5})])
    except ValueError as exc:
        message = str(exc)
        assert "atom 1" in message
        assert "constraint" in message
    else:  # pragma: no cover
        raise AssertionError(
            "a removed atom under a constraint must refuse, not silently drop the reference"
        )


# --- the metric: PBC minimum-image vs plain Cartesian, stated in the record ----------------


def test_deduplicate_uses_minimum_image_under_pbc_and_plain_cartesian_otherwise() -> None:
    # Two atoms one lattice vector apart: 3.8 Å and 0.2 Å in a 4 Å cubic cell. Plain
    # Cartesian distance is 3.6 Å (> 0.5); minimum-image under PBC is 0.4 Å (< 0.5). So
    # the same coordinates dedupe with a cell and do NOT dedupe without one — and the
    # recorded parameters/description state which metric was used.
    symbols = ["O", "O"]
    positions = np.array([[3.8, 0.0, 0.0], [0.2, 0.0, 0.0]], dtype=float)

    with_cell = CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=symbols, positions=positions),
                cell=Cell(lattice_vectors=4.0 * np.eye(3), pbc=(True, True, True)),
            )
        ],
        provenance=_provenance("pbc.vasp"),
    )
    without_cell = with_cell.model_copy(
        update={"frames": [with_cell.frames[0].model_copy(update={"cell": None})]}
    )

    pbc_repaired, pbc_record = _apply(with_cell, {"distance_threshold": 0.5})
    assert pbc_repaired.frames[0].atoms.symbols == ["O"]  # atom 1 removed (lowest survives)
    assert "minimum-image" in pbc_record.parameters["metric"]
    assert pbc_record.parameters["removed_atoms"] == [{"index": 1, "symbol": "O"}]
    assert "minimum-image" in pbc_record.description

    cartesian_repaired, cartesian_record = _apply(without_cell, {"distance_threshold": 0.5})
    assert cartesian_repaired.frames[0].atoms.symbols == ["O", "O"]  # nothing removed
    assert "plain Cartesian" in cartesian_record.parameters["metric"]
    assert cartesian_record.parameters["removed_atoms"] == []
    assert "plain Cartesian" in cartesian_record.description


# --- the recorded no-op --------------------------------------------------------------------


def test_deduplicate_nothing_to_remove_is_a_recorded_noop() -> None:
    # Threshold below every pair distance: empty removal, still a recorded, reproducible
    # repair — and no DEDUPE_REMOVED_ATOMS warning (nothing was lost).
    source = _duplicates_object()
    repaired, record = _apply(source, {"distance_threshold": 0.001})
    assert repaired.frames[0].atoms.symbols == source.frames[0].atoms.symbols
    assert record.parameters["removed_atoms"] == []
    assert record.hazards == []
    assert "nothing removed" in record.description


# --- flagship: convert + validate green + warning + reproduce byte-identically -------------


def test_deduplicate_flagship_converts_validates_and_reproduces() -> None:
    reg = _registry()
    source = _duplicates_object()

    result = _convert(
        source, reg=reg, repairs=[RepairRequest("deduplicate", {"distance_threshold": 0.5})]
    )
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The report's repairs section: one row with the complete recorded parameters —
    # threshold, metric, and the exact {index, symbol} removed set.
    (row,) = result.report.repairs
    assert row.choice == "deduplicate"
    assert row.parameters["distance_threshold"] == 0.5
    assert "minimum-image" in row.parameters["metric"]
    assert row.parameters["removed_atoms"] == [
        {"index": 1, "symbol": "Cl"},
        {"index": 2, "symbol": "Na"},
        {"index": 4, "symbol": "Na"},
    ]
    assert "removed 3 atom(s)" in row.description

    # The reductive-loss warning names the count, source="repair".
    assert [w.code for w in result.report.repair_warnings] == ["DEDUPE_REMOVED_ATOMS"]
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert "removed 3 atom(s)" in warning.message

    # Provenance carries the operation="repair" record referencing the same row id.
    repair_records = [r for r in result.canonical_out.provenance.history if r.operation == "repair"]
    assert len(repair_records) == 1
    assert repair_records[0].assumptions == [row.id]

    # Reproduce byte-identically from source + the report's recorded parameters alone.
    rederived = _convert(source, reg=reg, repairs=[RepairRequest(row.choice, dict(row.parameters))])
    assert rederived.output is not None and rederived.output == result.output
    assert rederived.validation is not None and rederived.validation.status == "passed"
