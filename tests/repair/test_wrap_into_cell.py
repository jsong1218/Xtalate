"""wrap-into-cell — the M64 flagship (v1.7 M64-S2; D251).

The version's contract, proven on the one operation with a physics-losing failure mode: an
unwrapped MD trajectory, wrapped on explicit request, converts and validates green, carries
the R5 warning in plain language, and re-derives byte-identically from source + the report's
recorded parameters. Also: the cell-less refusal composes with the existing ``missing_lattice``
recovery (nothing is fabricated; a pre-supplied choice resolves the block in place since
v1.7.1, D260), boundary handling is deterministic with the fold clamped into ``[0, 1)`` at
every precision (the subnormal-residue idempotence fix, D258→D260), the R5 warning is
suppressed on a no-op application, and the *transformative* hazard class is registered and
exercised.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from tests.conversion.test_engine import _parse, _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionResult
from xtalate.repair import (
    TRANSFORMATIVE_HAZARD,
    RepairRequest,
    apply_repairs,
)
from xtalate.repair.operations import WRAP_DISCARDS_UNWRAPPED_PATHS, WrapIntoCell
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame, Provenance
from xtalate.schema.cell import to_fractional

GOLDEN = Path(__file__).parent.parent / "golden"
XDATCAR = GOLDEN / "xdatcar" / "nacl-md-fixed-cell" / "XDATCAR"


def _convert(
    source: CanonicalObject,
    *,
    reg: Registry | None = None,
    repairs: list[RepairRequest] | None = None,
    target_format_id: str = "xdatcar",
    **kwargs: Any,
) -> ConversionResult:
    reg = reg or _registry()
    return ConversionEngine(reg).convert(
        source,
        source_format_id="xdatcar",
        target_format_id=target_format_id,
        source_filename="XDATCAR",
        repairs=repairs,
        **kwargs,
    )


def _parsed(reg: Registry) -> CanonicalObject:
    return _parse(reg, "xdatcar", XDATCAR)


def _unwrap(obj: CanonicalObject) -> CanonicalObject:
    """Deterministically push some atoms out of the cell across frames — an unwrapped MD
    trajectory (no RNG; integer lattice translations so wrap must recover the exact originals)."""
    frames: list[Frame] = []
    for i, frame in enumerate(obj.frames):
        assert frame.cell is not None  # the fixture's frames all carry a cell
        lattice = np.asarray(frame.cell.lattice_vectors, dtype=float)
        positions = np.asarray(frame.atoms.positions, dtype=float).copy()
        n = positions.shape[0]
        k = i % 4
        if k == 1:
            positions[0] = positions[0] + lattice[0]
            positions[n // 2] = positions[n // 2] - lattice[1]
        elif k == 2:
            positions[0] = positions[0] + lattice[0] + lattice[1]
            positions[n - 1] = positions[n - 1] - lattice[2]
        elif k == 3:
            positions[0] = positions[0] + 2.0 * lattice[0]
        frames.append(
            frame.model_copy(
                update={"atoms": frame.atoms.model_copy(update={"positions": positions})}
            )
        )
    return obj.model_copy(update={"frames": frames})


# --- the flagship: convert + validate green + R5 warning + reproduce from report ---------


def test_wrap_into_cell_flagship_converts_validates_and_reproduces() -> None:
    reg = _registry()
    parsed = _parsed(reg)
    original_positions = np.asarray(parsed.frames[1].atoms.positions, dtype=float)
    unwrapped = _unwrap(parsed)

    result = _convert(unwrapped, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The repaired object's positions are the original in-cell positions again — the wrap
    # exactly undoes the deterministic unwrapping (allclose: the solve has float noise).
    assert np.allclose(
        np.asarray(result.canonical_out.frames[1].atoms.positions, dtype=float),
        original_positions,
        atol=1e-9,
    )

    # The report's repairs section: one user-requested row with the complete parameters.
    (row,) = result.report.repairs
    assert row.choice == "wrap_into_cell"
    assert row.parameters == {}  # wrap takes no parameters; recorded verbatim (complete)
    assert "minimum-image" in row.description

    # The R5 warning appears in the repairs section (D251: plain language, never glossed).
    assert [w.code for w in result.report.repair_warnings] == ["WRAP_DISCARDS_UNWRAPPED_PATHS"]
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert "diffusion paths" in warning.message

    # Provenance carries the operation="repair" record referencing the same row id.
    history = result.canonical_out.provenance.history
    repair_records = [r for r in history if r.operation == "repair"]
    assert len(repair_records) == 1
    assert repair_records[0].assumptions == [row.id]

    # Reproduce byte-identically from source + the report's recorded parameters alone.
    rederived = _convert(
        unwrapped, reg=reg, repairs=[RepairRequest(row.choice, dict(row.parameters))]
    )
    assert rederived.output is not None and rederived.output == result.output
    assert rederived.validation is not None and rederived.validation.status == "passed"


def test_wrap_is_a_reference_application_within_the_engine() -> None:
    # The same operation applied through apply_repairs (the harness S1 proved) and through the
    # engine lands the same repaired object — one code path, two entry points.
    reg = _registry()
    unwrapped = _unwrap(_parsed(reg))
    outcome = apply_repairs(unwrapped, [RepairRequest("wrap_into_cell")])
    assert outcome.canonical is not None and not outcome.blocked
    assert [a.operation for a in outcome.applied] == ["wrap_into_cell"]
    assert [h.code for h in outcome.applied[0].hazards] == ["WRAP_DISCARDS_UNWRAPPED_PATHS"]

    engine = _convert(unwrapped, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert engine.canonical_out is not None
    for a, b in zip(outcome.canonical.frames, engine.canonical_out.frames, strict=True):
        assert np.array_equal(
            np.asarray(a.atoms.positions, dtype=float),
            np.asarray(b.atoms.positions, dtype=float),
        )


# --- the cell-less refusal composes with missing_lattice; nothing is fabricated -------------


def test_cell_less_wrap_refuses_via_missing_lattice() -> None:
    reg = _registry()
    parsed = _parsed(reg)
    cell_less = parsed.model_copy(
        update={"frames": [f.model_copy(update={"cell": None}) for f in parsed.frames]}
    )

    result = _convert(cell_less, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    assert "wrap_into_cell" in result.report.refusal["message"]
    assert "cell" in result.report.refusal["message"]

    # It resolves through the *existing* scenario, with the pair-specific option list.
    scenarios = result.report.refusal["unresolved_scenarios"]
    assert scenarios and scenarios[0]["scenario"] == "missing_lattice"
    assert scenarios[0]["path"] == "cell.lattice_vectors"
    assert scenarios[0]["options"]  # manual_input/bounding_box — the recovery machinery's own
    assert result.canonical_out is None  # nothing was fabricated, nothing was applied
    assert result.report.repairs == []  # no repair row on a refused-without-application set


def test_cell_less_wrap_resolves_in_place_with_presupplied_recovery() -> None:
    # v1.7.1 (D260): a blocked repair resolves in place when the caller pre-supplied the choice
    # its block scenario offers — the choice is applied to the object before the repair is
    # retried, so the cell-less wrap now completes instead of refusing (the v1.7 limitation).
    reg = _registry()
    parsed = _parsed(reg)
    cell_less = parsed.model_copy(
        update={"frames": [f.model_copy(update={"cell": None}) for f in parsed.frames]}
    )
    # manual_input with a lattice smaller than the trajectory's extent: the wrap genuinely
    # folds atoms into the supplied cell (a bounding_box choice would rigidly shift the atoms
    # into the box first, making the wrap a no-op — both behaviours are honest).
    choices = {
        "missing_lattice": {
            "choice": "manual_input",
            "parameters": {"lattice": [[2.5, 0.0, 0.0], [0.0, 2.5, 0.0], [0.0, 0.0, 2.5]]},
        }
    }

    result = _convert(
        cell_less, reg=reg, repairs=[RepairRequest("wrap_into_cell")], recovery_choices=choices
    )
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None

    # The report records application order: the recovery that un-blocked the wrap precedes
    # the wrap row, and the fabricated cell is accounted as supplied.
    rows = result.report.assumptions
    assert [a.id for a in rows] == ["A1", "A2"]
    assert [a.scenario for a in rows] == ["missing_lattice", "repair"]
    assert [a.choice for a in rows] == ["manual_input", "wrap_into_cell"]
    assert any(s.path == "cell.lattice_vectors" for s in result.report.supplied)
    # The wrap actually folded atoms into the supplied cell (atoms at 2.8 Å fold into the
    # 2.5 Å box), so R5 fires.
    assert [w.code for w in result.report.repair_warnings] == ["WRAP_DISCARDS_UNWRAPPED_PATHS"]

    # The wrapped positions lie inside the fabricated box (the minimum-image fold, in range).
    cell = result.canonical_out.frames[0].cell
    assert cell is not None  # the supplied lattice survived into the output object
    lattice = np.asarray(cell.lattice_vectors, dtype=float)
    frac = to_fractional(
        np.asarray(result.canonical_out.frames[0].atoms.positions, dtype=float), lattice
    )
    assert np.all((frac >= 0.0) & (frac < 1.0))

    # Reproduce byte-identically from source + the recorded rows alone — the repair replay
    # needs the same pre-supplied choice the report's recovery row records.
    replayed = [RepairRequest(r.choice, dict(r.parameters)) for r in result.report.repairs]
    rederived = _convert(cell_less, reg=reg, repairs=replayed, recovery_choices=choices)
    assert rederived.output is not None and rederived.output == result.output


def test_supplied_recovery_that_still_blocks_refuses_with_the_choice_carried() -> None:
    # v1.7.1 (D260): all-or-nothing survives the in-place resolution — a pre-supplied recovery
    # that *satisfies the scenario but not the repair* (a manual_input lattice that is itself
    # singular) leads to a refusal that carries the pre-repair Assumption: the caller's choice
    # is recorded as supplied, nothing is applied, and nothing is silently dropped.
    reg = _registry()
    parsed = _parsed(reg)
    cell_less = parsed.model_copy(
        update={"frames": [f.model_copy(update={"cell": None}) for f in parsed.frames]}
    )
    degenerate = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]  # zero volume
    choices = {"missing_lattice": {"choice": "manual_input", "parameters": {"lattice": degenerate}}}

    result = _convert(
        cell_less, reg=reg, repairs=[RepairRequest("wrap_into_cell")], recovery_choices=choices
    )
    assert result.report.status == "refused"
    assert result.canonical_out is None  # nothing was applied
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    assert "singular" in result.report.refusal["message"]
    # The caller's own choice is honestly recorded (the cell was supplied), and the wrap
    # never ran — the refusal names the same missing_lattice block, answerable again.
    (row,) = result.report.assumptions
    assert (row.id, row.scenario, row.choice) == ("A1", "missing_lattice", "manual_input")
    assert any(s.path == "cell.lattice_vectors" for s in result.report.supplied)
    assert result.report.repairs == []


def test_pre_flight_refusal_after_pre_repair_carries_recovery_and_repair_rows() -> None:
    # v1.7.1 (D260): when the pre-supplied recovery un-blocks the repair but a *pre-flight*
    # scenario is still unanswered (a multi-frame source to a single-frame POSCAR target with no
    # frame_selection choice), the refusal carries the pre-repair recovery row AND the repair
    # row — nothing applied beyond the caller's choice, nothing recorded as if it had been.
    reg = _registry()
    parsed = _parsed(reg)  # multi-frame, cells stripped below
    cell_less = parsed.model_copy(
        update={"frames": [f.model_copy(update={"cell": None}) for f in parsed.frames]}
    )
    choices = {
        "missing_lattice": {
            "choice": "manual_input",
            "parameters": {"lattice": [[2.5, 0.0, 0.0], [0.0, 2.5, 0.0], [0.0, 0.0, 2.5]]},
        }
    }
    result = _convert(
        cell_less,
        reg=reg,
        repairs=[RepairRequest("wrap_into_cell")],
        recovery_choices=choices,
        target_format_id="poscar",
    )
    assert result.report.status == "refused"
    refusal = result.report.refusal
    assert refusal is not None and refusal["code"] == "RECOVERY_REQUIRED"
    # The unanswered scenario is the *pre-flight* one (POSCAR keeps one frame); the cell
    # question is settled.
    scenarios = {s["scenario"] for s in refusal["unresolved_scenarios"]}
    assert scenarios == {"frame_selection"}
    # Application order is recorded even on a refusal: the recovery that un-blocked the wrap
    # precedes the wrap row.
    assert [(a.id, a.scenario, a.choice) for a in result.report.assumptions] == [
        ("A1", "missing_lattice", "manual_input"),
        ("A2", "repair", "wrap_into_cell"),
    ]
    assert any(s.path == "cell.lattice_vectors" for s in result.report.supplied)


def test_pre_repair_and_pre_flight_recovery_are_recorded_in_application_order() -> None:
    # v1.7.1 (D260): the full pipeline with both recovery stages — a pre-repair choice that
    # un-blocks the wrap AND a pre-flight choice the target needs — records contiguous A1..
    # rows in application order: missing_lattice → wrap → frame_selection.
    reg = _registry()
    parsed = _parsed(reg)
    cell_less = parsed.model_copy(
        update={"frames": [f.model_copy(update={"cell": None}) for f in parsed.frames]}
    )
    choices = {
        "missing_lattice": {
            "choice": "manual_input",
            "parameters": {"lattice": [[2.5, 0.0, 0.0], [0.0, 2.5, 0.0], [0.0, 0.0, 2.5]]},
        },
        "frame_selection": {"choice": "last"},
    }
    result = _convert(
        cell_less,
        reg=reg,
        repairs=[RepairRequest("wrap_into_cell")],
        recovery_choices=choices,
        target_format_id="poscar",
    )
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert [(a.id, a.scenario, a.choice) for a in result.report.assumptions] == [
        ("A1", "missing_lattice", "manual_input"),
        ("A2", "repair", "wrap_into_cell"),
        ("A3", "frame_selection", "last"),
    ]


def test_degenerate_cell_blocks_too() -> None:
    reg = _registry()
    parsed = _parsed(reg)
    frame = parsed.frames[0]
    degenerate = frame.model_copy(
        update={"cell": Cell(lattice_vectors=np.zeros((3, 3)), pbc=(True, True, True))}
    )
    obj = parsed.model_copy(update={"frames": [degenerate, *parsed.frames[1:]]})

    result = _convert(obj, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    assert "singular" in result.report.refusal["message"]


# --- deterministic boundary handling ------------------------------------------------------


def _cubic(fractional_rows: np.ndarray) -> CanonicalObject:
    lattice = 2.0 * np.eye(3)  # a = b = c = 2 Å, orthogonal — all test coords are exact.
    positions = np.asarray(fractional_rows, dtype=float) @ lattice
    frame = Frame(
        index=0,
        atoms=AtomsBlock(
            symbols=["H", "He", "Li", "Be", "B"][: len(positions)], positions=positions
        ),
        cell=Cell(lattice_vectors=lattice, pbc=(True, True, True)),
    )
    return CanonicalObject(
        frames=[frame],
        provenance=Provenance(
            source_filename="boundary.xyz",
            source_format="extxyz",
            original_coordinate_system="cartesian",
        ),
    )


def test_wrap_boundary_handling_is_deterministic() -> None:
    # Fractional coords on faces/edges and across the origin: 1.0 -> 0.0, 2.25 -> 0.25,
    # -0.5 -> 0.5, -0.25 -> 0.75; 0.5 (exactly mid-face) stays 0.5.
    obj = _cubic(
        np.array(
            [
                [1.0, 0.0, 0.0],
                [0.5, 0.0, 0.0],
                [-0.5, 0.0, 0.0],
                [2.25, 0.0, 0.0],
                [-0.25, 0.0, 0.0],
            ]
        )
    )
    outcome = apply_repairs(obj, [RepairRequest("wrap_into_cell")])
    assert outcome.canonical is not None and not outcome.blocked
    wrapped = np.asarray(outcome.canonical.frames[0].atoms.positions, dtype=float)
    expected = np.array(
        [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [0.5, 0.0, 0.0], [0.25, 0.0, 0.0], [0.75, 0.0, 0.0]]
    ) @ (2.0 * np.eye(3))
    assert np.array_equal(wrapped, expected)

    # The same input lands the same output on every run — and the engine path agrees.
    again = apply_repairs(obj, [RepairRequest("wrap_into_cell")])
    assert again.canonical is not None
    assert np.array_equal(
        np.asarray(again.canonical.frames[0].atoms.positions, dtype=float), wrapped
    )
    reg = _registry()
    converted = _convert(obj, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert converted.canonical_out is not None
    assert np.array_equal(
        np.asarray(converted.canonical_out.frames[0].atoms.positions, dtype=float), wrapped
    )


def test_wrap_fold_stays_inside_half_open_interval_at_boundary_residues() -> None:
    # v1.7.1 (D260; the M67-S1 property find): a coordinate within float-underflow of a cell
    # face (a residue below the ULP of 1.0, ~2.2e-16) still folds inside [0, 1) — 1 - eps is
    # not representable and np.mod(-eps, 1.0) rounds to exactly 1.0, which the fold clamps to
    # 0.0 (the minimum-image value of a coordinate on a face). The fold is therefore
    # idempotent at every precision.
    eps = 1e-17  # below ULP(1.0): both 1 - eps and mod(-eps, 1.0) round to 1.0
    obj = _cubic(np.array([[1.0 - eps, 0.0, 0.0], [-eps, 0.0, 0.0], [0.5, 0.0, 0.0]]))
    once = apply_repairs(obj, [RepairRequest("wrap_into_cell")])
    assert once.canonical is not None and not once.blocked
    wrapped = np.asarray(once.canonical.frames[0].atoms.positions, dtype=float)
    # Both boundary coordinates land on 0.0 (the face), never on 1.0; 0.5 stays 0.5.
    expected = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]) @ (2.0 * np.eye(3))
    assert np.array_equal(wrapped, expected)
    # A second application is a true no-op — idempotent at the boundary.
    twice = apply_repairs(once.canonical, [RepairRequest("wrap_into_cell")])
    assert twice.canonical is not None
    assert np.array_equal(
        np.asarray(twice.canonical.frames[0].atoms.positions, dtype=float), wrapped
    )


def test_wrap_noop_suppresses_the_r5_warning() -> None:
    # v1.7.1 (D260): a wrap that moves no position discards no trajectory information, so the
    # R5 statement is suppressed — the dedupe/identity-permutation precedent: a no-op repair
    # must not claim a loss. An application that actually folds atoms still warns (the
    # flagship above).
    reg = _registry()
    obj = _cubic(np.array([[0.1, 0.0, 0.0], [0.5, 0.0, 0.0], [0.9, 0.2, 0.7]]))  # in-cell

    outcome = apply_repairs(obj, [RepairRequest("wrap_into_cell")])
    assert outcome.canonical is not None and not outcome.blocked
    (record,) = outcome.applied
    assert record.hazards == []

    # The engine path agrees: a completed wrap of an already-in-cell structure reports no
    # repair warning.
    result = _convert(obj, reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    assert result.report.status == "completed"
    assert result.report.repair_warnings == []


# --- the transformative hazard class (D251) ------------------------------------------------


def test_transformative_hazard_class_is_registered_and_exercised() -> None:
    # The class exists, wrap declares it, and it is not a recovery scenario — repairs are not
    # recovery scenarios (the class is a repair-side declaration, Part 4 §3.1's fourth class).
    assert TRANSFORMATIVE_HAZARD == "transformative"
    assert WrapIntoCell.hazard_class == TRANSFORMATIVE_HAZARD
    assert WrapIntoCell.hazards == (WRAP_DISCARDS_UNWRAPPED_PATHS,)
    assert WRAP_DISCARDS_UNWRAPPED_PATHS.code == "WRAP_DISCARDS_UNWRAPPED_PATHS"

    # Exercised end to end: the warning row is source="repair" with the R5 text verbatim.
    reg = _registry()
    result = _convert(_unwrap(_parsed(reg)), reg=reg, repairs=[RepairRequest("wrap_into_cell")])
    (warning,) = result.report.repair_warnings
    assert warning.source == "repair"
    assert warning.code == WRAP_DISCARDS_UNWRAPPED_PATHS.code
    assert warning.message == WRAP_DISCARDS_UNWRAPPED_PATHS.message


# --- pbc-aware wrap (v1.7.1 arch review, REPAIR-C1) ---------------------------------------


def _one_frame(positions: np.ndarray, pbc: tuple[bool, bool, bool]) -> CanonicalObject:
    """A single-frame object, 4 Å cubic cell, with the given per-axis periodicity."""
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=["Ar", "Ar"], positions=positions),
                cell=Cell(lattice_vectors=4.0 * np.eye(3), pbc=pbc),
            )
        ],
        provenance=Provenance(
            source_filename="slab.xyz",
            source_format="extxyz",
            original_coordinate_system="cartesian",
        ),
    )


def test_wrap_leaves_a_non_periodic_axis_untouched() -> None:
    # Atom 1 sits 6 Å up z (1.5 cells) above a slab; z is non-periodic (vacuum gap).
    positions = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 6.0]], dtype=float)
    obj = _one_frame(positions, pbc=(True, True, False))
    wrapped = WrapIntoCell().apply(obj, {})
    out = np.asarray(wrapped.frames[0].atoms.positions, dtype=float)
    # z is NOT folded — the adsorbate stays 6 Å up, not translated through the vacuum to 2 Å.
    assert out[1, 2] == 6.0
    # An in-cell x/y stays put too (already inside).
    np.testing.assert_allclose(out[:, :2], positions[:, :2])


def test_wrap_folds_only_the_periodic_axes() -> None:
    # x is 5 Å (1.25 cells) — periodic, folds to 1.0; z is 6 Å — non-periodic, stays.
    positions = np.array([[0.0, 0.0, 0.0], [5.0, 1.0, 6.0]], dtype=float)
    obj = _one_frame(positions, pbc=(True, True, False))
    out = np.asarray(WrapIntoCell().apply(obj, {}).frames[0].atoms.positions, dtype=float)
    np.testing.assert_allclose(out[1], [1.0, 1.0, 6.0])
    # A real move on a periodic axis still arms the R5 warning.
    assert WrapIntoCell().hazards_for(obj, {}) == [WRAP_DISCARDS_UNWRAPPED_PATHS]


def test_wrap_on_a_fully_non_periodic_cell_is_a_no_op() -> None:
    # A cluster in a bounding box declares no periodic direction — nothing is wrapped, and
    # (a no-op repair must not claim a loss, D260) the R5 warning is suppressed.
    positions = np.array([[0.0, 0.0, 0.0], [5.0, 6.0, 7.0]], dtype=float)
    obj = _one_frame(positions, pbc=(False, False, False))
    out = np.asarray(WrapIntoCell().apply(obj, {}).frames[0].atoms.positions, dtype=float)
    np.testing.assert_allclose(out, positions)
    assert WrapIntoCell().hazards_for(obj, {}) == []


def test_wrap_describe_does_not_claim_loss_on_a_no_op() -> None:
    positions = np.array([[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]], dtype=float)  # both in-cell
    obj = _one_frame(positions, pbc=(True, True, True))
    op = WrapIntoCell()
    assert op.hazards_for(obj, {}) == []  # already suppressed (D260)
    text = op.describe(obj, {})
    assert "not recoverable" not in text  # the description must not claim a loss either
    assert "already" in text.lower() or "no atom" in text.lower()
