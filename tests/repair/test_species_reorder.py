"""species reorder + the shared per-atom reindex spine (v1.7 M65-S1; D252).

S1 builds the single helper that reindexes **every** per-atom array/reference
consistently across the four schema locations, and proves it on the safe,
non-destructive operation: a reindex bug surfaces as \"the output is not a valid
rearrangement of the input\", with no loss to reason through. One test per per-atom
category — positions, masses, occupancies, velocities, forces, charges,
magnetic_moments, ``custom_per_atom`` (ndarray and list forms), and
``constraints[].atom_indices`` remap — plus the trajectory-wide frame-invariance,
the already-grouped identity edge (advisory suppressed), the exporter lockstep, the
flagship end-to-end reproducibility, and the POSCAR compose-without-double-counting
proof.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from tests.conversion.test_engine import _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.exporters._common import group_by_element
from xtalate.exporters.poscar import PoscarExporter
from xtalate.repair import RepairRequest, apply_repairs, get_operation
from xtalate.repair.operations import (
    ATOM_ORDER_CHANGED,
    SpeciesReorder,
    _element_grouping_permutation,
)
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

#: The species-reorder permutation for the shared fixture's symbols below
#: (["Na", "Cl", "Na", "Cl", "Cl", "Na"]): first-appearance element order Na, Cl;
#: stable within each element. Non-identity — a category that fails to follow the map
#: is caught by a direct comparison against PERM.
SYMBOLS = ["Na", "Cl", "Na", "Cl", "Cl", "Na"]
PERM = [0, 2, 5, 1, 3, 4]
INVERSE = {old: new for new, old in enumerate(PERM)}
N = len(SYMBOLS)


def _provenance(filename: str = "rich.vasp") -> Provenance:
    return Provenance(
        source_filename=filename,
        source_format="poscar",
        original_coordinate_system="cartesian",
    )


def _rich_object() -> CanonicalObject:
    """A single-frame object with **every** per-atom array/reference populated, in a
    deliberately element-ungrouped order. Per-atom values are distinct so any category
    that fails to follow the map is caught by a direct array comparison."""
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=SYMBOLS,
            positions=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 1.0, 1.0],
                    [2.0, 0.0, 0.0],
                    [3.0, 1.0, 0.0],
                    [4.0, 0.0, 1.0],
                    [5.0, 1.0, 1.0],
                ],
                dtype=float,
            ),
            masses=np.array([22.99, 35.45, 22.99, 35.45, 35.45, 22.99]),
            occupancies=[1.0, 0.5, 1.0, 0.75, 0.5, 1.0],
        ),
        cell=Cell(lattice_vectors=6.0 * np.eye(3), pbc=(True, True, True)),
        dynamics=Dynamics(
            velocities=np.array(
                [
                    [0.0, 0.0, 0.1],
                    [0.2, 0.0, 0.0],
                    [0.0, 0.3, 0.0],
                    [0.4, 0.0, 0.0],
                    [0.0, 0.0, 0.5],
                    [0.6, 0.0, 0.0],
                ],
                dtype=float,
            ),
            forces=np.array(
                [
                    [0.0, 0.1, 0.0],
                    [0.0, 0.0, 0.2],
                    [0.3, 0.0, 0.0],
                    [0.0, 0.4, 0.0],
                    [0.0, 0.0, 0.5],
                    [0.6, 0.0, 0.0],
                ],
                dtype=float,
            ),
            constraints=[Constraint(kind="fixed_atoms", atom_indices=[1, 4])],
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


def _lean_object() -> CanonicalObject:
    """The flagship's source: element-ungrouped, single frame, cell — nothing else, so the
    POSCAR round-trip preserves every path (no removals to complicate byte-identity)."""
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=SYMBOLS,
            positions=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 1.0, 1.0],
                    [2.0, 0.0, 0.0],
                    [3.0, 1.0, 0.0],
                    [4.0, 0.0, 1.0],
                    [5.0, 1.0, 1.0],
                ],
                dtype=float,
            ),
        ),
        cell=Cell(lattice_vectors=6.0 * np.eye(3), pbc=(True, True, True)),
    )
    return CanonicalObject(frames=[frame], provenance=_provenance("lean.vasp"))


def _trajectory_object() -> CanonicalObject:
    """A 3-frame trajectory with the same (ungrouped) atom identity per frame and
    frame-distinct positions/velocities — the reorder test must apply one permutation."""
    symbols = ["Na", "Cl", "Na", "Cl"]
    frames: list[Frame] = []
    for i in range(3):
        frames.append(
            Frame(
                index=i,
                atoms=AtomsBlock(
                    symbols=symbols,
                    positions=np.array(
                        [
                            [0.0 + i, 0.0, 0.0],
                            [1.0, 1.0 + i, 0.0],
                            [2.0, 0.0, 2.0 + i],
                            [3.0, 3.0, 3.0 + i],
                        ],
                        dtype=float,
                    ),
                ),
                cell=Cell(lattice_vectors=10.0 * np.eye(3), pbc=(True, True, True)),
                dynamics=Dynamics(
                    velocities=np.array(
                        [
                            [0.1 * i, 0.0, 0.0],
                            [0.0, 0.1 * i, 0.0],
                            [0.0, 0.0, 0.1 * i],
                            [0.1 * i, 0.1 * i, 0.1 * i],
                        ],
                        dtype=float,
                    )
                ),
            )
        )
    return CanonicalObject(frames=frames, provenance=_provenance("traj.vasp"))


def _apply(obj: CanonicalObject) -> tuple[CanonicalObject, Any]:
    outcome = apply_repairs(obj, [RepairRequest("species_reorder")])
    assert outcome.canonical is not None and not outcome.blocked
    assert [a.operation for a in outcome.applied] == ["species_reorder"]
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


# --- registration + non-destructive posture -------------------------------------------------


def test_species_reorder_is_registered_and_non_destructive() -> None:
    op = get_operation("species_reorder")
    assert isinstance(op, SpeciesReorder)
    assert op.operation == "species_reorder"
    # A permutation is fully recoverable from its map: no hazard class, and the advisory
    # is an order-changed courtesy for downstream tools, not a transformative-loss claim.
    assert op.hazard_class is None
    assert op.hazards == (ATOM_ORDER_CHANGED,)
    assert ATOM_ORDER_CHANGED.code == "ATOM_ORDER_CHANGED"
    assert "recoverable" in ATOM_ORDER_CHANGED.message


# --- one test per per-atom category: each array follows the permutation map ----------------


def test_species_reorder_permutes_symbols_and_positions() -> None:
    repaired, _ = _apply(_rich_object())
    atoms = repaired.frames[0].atoms
    assert atoms.symbols == ["Na", "Na", "Na", "Cl", "Cl", "Cl"]
    assert atoms.atomic_numbers == [11, 11, 11, 17, 17, 17]
    expected_positions = np.asarray(_rich_object().frames[0].atoms.positions)[PERM]
    assert np.array_equal(np.asarray(atoms.positions), expected_positions)


def test_species_reorder_permutes_masses() -> None:
    source = _rich_object()
    source_masses = source.frames[0].atoms.masses
    assert source_masses is not None
    repaired, _ = _apply(source)
    repaired_masses = repaired.frames[0].atoms.masses
    assert repaired_masses is not None
    assert np.array_equal(repaired_masses, source_masses[PERM])


def test_species_reorder_permutes_occupancies() -> None:
    source = _rich_object()
    source_occupancies = source.frames[0].atoms.occupancies
    assert source_occupancies is not None
    repaired, _ = _apply(source)
    assert repaired.frames[0].atoms.occupancies == [source_occupancies[i] for i in PERM]


def test_species_reorder_permutes_velocities() -> None:
    source = _rich_object()
    source_velocities = source.frames[0].dynamics.velocities
    assert source_velocities is not None
    repaired, _ = _apply(source)
    repaired_velocities = repaired.frames[0].dynamics.velocities
    assert repaired_velocities is not None
    assert np.array_equal(repaired_velocities, source_velocities[PERM])


def test_species_reorder_permutes_forces() -> None:
    source = _rich_object()
    source_forces = source.frames[0].dynamics.forces
    assert source_forces is not None
    repaired, _ = _apply(source)
    repaired_forces = repaired.frames[0].dynamics.forces
    assert repaired_forces is not None
    assert np.array_equal(repaired_forces, source_forces[PERM])


def test_species_reorder_permutes_charges() -> None:
    source = _rich_object()
    source_charges = source.frames[0].electronic.charges
    assert source_charges is not None
    repaired, _ = _apply(source)
    repaired_charges = repaired.frames[0].electronic.charges
    assert repaired_charges is not None
    assert np.array_equal(repaired_charges, source_charges[PERM])


def test_species_reorder_permutes_magnetic_moments() -> None:
    source = _rich_object()
    source_moments = source.frames[0].electronic.magnetic_moments
    assert source_moments is not None
    repaired, _ = _apply(source)
    repaired_moments = repaired.frames[0].electronic.magnetic_moments
    assert repaired_moments is not None
    assert np.array_equal(repaired_moments, source_moments[PERM])


def test_species_reorder_permutes_custom_per_atom_ndarray_form() -> None:
    source = _rich_object()
    source_tags = source.user_metadata.custom_per_atom["tags"]
    assert isinstance(source_tags, np.ndarray)
    repaired, _ = _apply(source)
    tags = repaired.user_metadata.custom_per_atom["tags"]
    assert isinstance(tags, np.ndarray)
    assert np.array_equal(tags, source_tags[PERM])


def test_species_reorder_permutes_custom_per_atom_list_form() -> None:
    source = _rich_object()
    source_labels = source.user_metadata.custom_per_atom["labels"]
    assert isinstance(source_labels, list)
    repaired, _ = _apply(source)
    labels = repaired.user_metadata.custom_per_atom["labels"]
    assert isinstance(labels, list)
    assert labels == [source_labels[i] for i in PERM]


def test_species_reorder_remaps_constraint_references() -> None:
    source = _rich_object()
    repaired, _ = _apply(source)
    (constraint,) = repaired.frames[0].dynamics.constraints or []
    assert constraint.kind == "fixed_atoms"
    # References follow the inverse permutation: source atoms 1 and 4 land at 3 and 5.
    assert constraint.atom_indices == [INVERSE[1], INVERSE[4]]


# --- trajectory: one frame-invariant permutation applied to every frame ---------------------


def test_species_reorder_reindexes_a_trajectory_identically_across_frames() -> None:
    source = _trajectory_object()
    repaired, record = _apply(source)
    perm = record.parameters["permutation"]
    assert perm == [0, 2, 1, 3]  # ["Na", "Cl", "Na", "Cl"] -> Na Na Cl Cl
    for out, src in zip(repaired.frames, source.frames, strict=True):
        assert out.atoms.symbols == ["Na", "Na", "Cl", "Cl"]
        assert np.array_equal(
            np.asarray(out.atoms.positions), np.asarray(src.atoms.positions)[perm]
        )
        assert out.dynamics.velocities is not None and src.dynamics.velocities is not None
        assert np.array_equal(out.dynamics.velocities, src.dynamics.velocities[perm])
    # Frame 0's symbols define the permutation; every frame followed it — nothing is
    # frame-dependent in the repair (the property that makes reorder safe on trajectories).
    assert repaired.frames[0].atoms.symbols == repaired.frames[1].atoms.symbols


# --- the already-grouped edge: identity permutation, advisory suppressed --------------------


def test_species_reorder_identity_when_already_grouped_suppresses_advisory() -> None:
    lean = _lean_object()
    grouped = lean.model_copy(
        update={
            "frames": [
                lean.frames[0].model_copy(
                    update={
                        "atoms": lean.frames[0].atoms.model_copy(
                            update={"symbols": ["Na", "Na", "Na", "Cl", "Cl", "Cl"]}
                        )
                    }
                )
            ]
        }
    )
    repaired, record = _apply(grouped)
    assert record.parameters == {"permutation": list(range(N))}
    assert record.hazards == []  # the advisory would be a lie: nothing changed
    assert "already element-grouped" in record.description
    assert np.array_equal(
        np.asarray(repaired.frames[0].atoms.positions),
        np.asarray(grouped.frames[0].atoms.positions),
    )


# --- the contract: recorded parameters are replayed, and invalid records are refused --------


def test_species_reorder_records_the_permutation_map_it_applied() -> None:
    _, record = _apply(_rich_object())
    assert record.parameters == {"permutation": PERM}
    # The reproducibility contract: apply(source, recorded parameters) lands the same object.
    replay = apply_repairs(
        _rich_object(), [RepairRequest("species_reorder", dict(record.parameters))]
    )
    assert replay.canonical is not None
    again, _ = _apply(_rich_object())
    assert np.array_equal(
        np.asarray(replay.canonical.frames[0].atoms.positions),
        np.asarray(again.frames[0].atoms.positions),
    )


def test_species_reorder_rejects_a_non_permutation_record() -> None:
    source = _rich_object()
    try:
        apply_repairs(source, [RepairRequest("species_reorder", {"permutation": [0, 1, 2]})])
    except ValueError as exc:
        assert "permutation" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a truncated permutation must be refused, not silently applied")


def test_species_reorder_supplied_arbitrary_permutation_is_not_called_element_regroup() -> None:
    # A caller-supplied permutation is validated only to be a permutation of range(N) — NOT
    # that it groups by element. A non-element-grouped map (here reverse order) must not be
    # described as "Regrouped atoms by element", which would be a false report entry (P1).
    arbitrary = [5, 4, 3, 2, 1, 0]  # a valid permutation of range(6), not the element grouping
    assert arbitrary != PERM and arbitrary != list(range(N))
    outcome = apply_repairs(
        _rich_object(), [RepairRequest("species_reorder", {"permutation": arbitrary})]
    )
    assert outcome.canonical is not None
    (record,) = outcome.applied
    assert record.parameters == {"permutation": arbitrary}
    assert "Regrouped atoms by element" not in record.description
    assert "supplied permutation map" in record.description


# --- the exporter lockstep: the repaired object is what an element-grouping exporter expects --


def test_species_reorder_grouping_matches_the_exporter_rule() -> None:
    # repair may not import exporters (layering), so the grouping rule is reimplemented in
    # repair/operations.py; this test pins the two to each other so the repaired object is
    # exactly the object an element-grouping exporter (POSCAR) writes — no double-counting.
    for symbols in (["Na", "Cl", "Na", "Cl", "Cl", "Na"], ["O", "O", "H", "H"], ["Fe", "O"]):
        assert _element_grouping_permutation(symbols) == group_by_element(symbols)[1]


# --- flagship: convert + validate green + advisory + reproduce byte-identically -------------


def test_species_reorder_flagship_converts_validates_and_reproduces() -> None:
    reg = _registry()
    source = _lean_object()

    result = _convert(source, reg=reg, repairs=[RepairRequest("species_reorder")])
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The repaired object is element-grouped, positions following the recorded map.
    assert result.canonical_out.frames[0].atoms.symbols == ["Na", "Na", "Na", "Cl", "Cl", "Cl"]

    # The report's repairs section: one row with the complete recorded parameters.
    (row,) = result.report.repairs
    assert row.choice == "species_reorder"
    assert row.parameters == {"permutation": PERM}
    assert "Regrouped atoms by element" in row.description

    # The advisory rides the existing hazards->warnings channel, source="repair".
    assert [w.code for w in result.report.repair_warnings] == ["ATOM_ORDER_CHANGED"]
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert "recoverable from the recorded permutation map" in warning.message

    # Provenance carries the operation="repair" record referencing the same row id.
    repair_records = [r for r in result.canonical_out.provenance.history if r.operation == "repair"]
    assert len(repair_records) == 1
    assert repair_records[0].assumptions == [row.id]

    # Reproduce byte-identically from source + the report's recorded parameters alone.
    rederived = _convert(source, reg=reg, repairs=[RepairRequest(row.choice, dict(row.parameters))])
    assert rederived.output is not None and rederived.output == result.output
    assert rederived.validation is not None and rederived.validation.status == "passed"


def test_species_reorder_composes_with_poscar_without_double_counting() -> None:
    # The repaired object IS the expected object (D20): POSCAR groups by element, so once
    # the repair has grouped the object, the exporter's own permutation is the identity —
    # applying it "on top" is a no-op, and the write/validate round-trip stays green.
    reg = _registry()
    result = _convert(_lean_object(), reg=reg, repairs=[RepairRequest("species_reorder")])
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The exporter's map over the repaired (grouped) expected object is identity — the
    # repair did not leave a state that double-permutes on write.
    assert PoscarExporter().atom_permutation(result.canonical_out) is None

    # And the written file is element-grouped: species line "Na Cl", counts "3 3".
    assert result.output is not None
    lines = result.output.decode().splitlines()
    assert lines[5] == "Na Cl"
    assert lines[6] == "3 3"
