"""The repair-engine contract and pipeline placement (v1.7 M64-S1; D249/D250).

S1 proves the *recording spine* on the reference operation (``identity``) before the hard
operation (wrap) lands: an ordered, recorded, reproducible repair running through the full
``parse → repair → pre-flight → export → validate`` pipeline, with the order recorded and a
no-repair conversion untouched (the byte-identity guarantee is structural — repairs add no
serialized field, so a repair-free report is byte-identical to the pre-v1.7 report; the full
suite below is the regression net).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np

from tests.conversion.test_engine import _parse, _registry
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport, ConversionResult
from xtalate.conversion.report import REPAIR_SCENARIO
from xtalate.recovery.scenarios import SCENARIO_HAZARD
from xtalate.repair import (
    REPAIR_BLOCK_MISSING_LATTICE,
    RepairBlock,
    RepairError,
    RepairOperation,
    RepairRequest,
    apply_repairs,
    get_operation,
)
from xtalate.repair.operations import IdentityRepair
from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame, Provenance

GOLDEN = Path(__file__).parent.parent / "golden"


def _poscar_nacl(reg: Registry | None = None) -> CanonicalObject:
    reg = reg or _registry()
    return _parse(reg, "poscar", GOLDEN / "poscar" / "nacl-primitive" / "POSCAR")


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
        source_filename="POSCAR",
        repairs=repairs,
        **kwargs,
    )


# --- contract: pure, deterministic, serializable parameters --------------------------------


def test_the_block_lattice_constant_stays_in_lockstep_with_the_registered_scenario() -> None:
    # Repair may not import recovery (layering); the one string they share is guarded here so the
    # repair refusal can never drift from the registered scenario code it resolves through.
    assert REPAIR_BLOCK_MISSING_LATTICE in SCENARIO_HAZARD


def test_operations_declare_the_closed_names() -> None:
    # The registry resolves by name and an unknown name raises a RepairError naming the closed
    # set. M64-S2 registers wrap-into-cell alongside the reference operation.
    assert get_operation("identity").operation == "identity"
    assert get_operation("wrap_into_cell").operation == "wrap_into_cell"
    try:
        get_operation("not_an_operation")
    except RepairError as exc:
        assert "identity" in str(exc) and "wrap_into_cell" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unregistered operation must raise RepairError")


def test_parameters_must_be_json_serializable() -> None:
    source = _poscar_nacl()
    try:
        apply_repairs(source, [RepairRequest("identity", {"payload": np.zeros(3)})])
    except RepairError as exc:
        assert "JSON-serializable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a numpy array parameter must be refused, not silently recorded")


def test_malformed_requests_and_operations_raise_repair_error() -> None:
    source = _poscar_nacl()

    # Parameters must be a dict, not e.g. a bare list.
    non_dict: Any = [1, 2, 3]
    try:
        apply_repairs(source, [RepairRequest("identity", non_dict)])
    except RepairError as exc:
        assert "must be a dict" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-dict parameters must be refused")

    # Requests must be RepairRequest objects.
    try:
        apply_repairs(source, [{"operation": "identity"}])  # type: ignore[list-item]
    except RepairError as exc:
        assert "RepairRequest" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a bare dict is not a repair request")

    # An unknown operation inside apply_repairs raises the same closed-set error as get_operation.
    try:
        apply_repairs(source, [RepairRequest("not_an_operation")])
    except RepairError as exc:
        assert "not_an_operation" in str(exc) and "identity" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("an unregistered operation must raise RepairError")

    # An operation declaring no name, and a duplicate name, are both refused at table build.
    class _Nameless(RepairOperation):
        operation = ""

        def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
            return obj

        def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
            return "nameless"

    try:
        apply_repairs(source, [], operations=[_Nameless()])
    except RepairError as exc:
        assert "non-empty name" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a nameless operation must be refused")

    try:
        apply_repairs(source, [], operations=[IdentityRepair(), IdentityRepair()])
    except RepairError as exc:
        assert "duplicate" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a duplicate operation name must be refused")


def test_repair_is_all_or_nothing_and_never_mutates_the_source() -> None:
    # A later op that blocks the set discards the earlier (already applied-to-a-copy) ones: no
    # partial repair is ever presented as complete, and the caller's object is untouched. The
    # blocker is a test-only operation injected through the registry seam — no real operation
    # ships in S1 that can block.
    class _Blocker(RepairOperation):
        operation = "blocker"

        def block(self, obj: CanonicalObject, parameters: dict[str, Any]) -> RepairBlock:
            return RepairBlock(
                operation=self.operation,
                reason=REPAIR_BLOCK_MISSING_LATTICE,
                path="cell.lattice_vectors",
                detail="blocks for the all-or-nothing test",
            )

        def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
            return obj

        def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
            return "blocker"

    source = _poscar_nacl()
    before = source.frames[0].atoms.positions.copy()
    outcome = apply_repairs(
        source,
        [RepairRequest("identity"), RepairRequest("blocker")],
        operations=[IdentityRepair(), _Blocker()],
    )
    assert outcome.canonical is None
    assert outcome.applied == []  # nothing recorded, nothing committed
    assert outcome.blocked and outcome.blocked[0].operation == "blocker"
    assert outcome.blocked[0].reason == REPAIR_BLOCK_MISSING_LATTICE
    assert np.array_equal(source.frames[0].atoms.positions, before)


# --- pipeline placement (S1 done-means) ----------------------------------------------------


def test_identity_repair_runs_the_full_pipeline_and_records_the_triple() -> None:
    source = _poscar_nacl()
    result = _convert(source, repairs=[RepairRequest("identity", {"step": 1})])
    assert result.report.status == "completed"
    assert result.validation is not None and result.validation.status == "passed"
    assert result.canonical_out is not None
    canonical_out = result.canonical_out

    # The report's user-requested repairs section holds exactly one row (D249 (a)+(b)).
    assert result.report.repairs == result.report.assumptions  # nothing else assumed
    (row,) = result.report.repairs
    assert row.scenario == REPAIR_SCENARIO
    assert row.choice == "identity"
    assert row.parameters == {"step": 1}
    assert row.origin == "preset"
    assert "no scientific value changed" in row.description

    # (c) — a ConversionRecord(operation="repair") in provenance, referencing the row id.
    history = canonical_out.provenance.history
    repair_records = [r for r in history if r.operation == "repair"]
    assert len(repair_records) == 1
    assert repair_records[0].assumptions == [row.id]

    # Identity changed nothing: the exported canonical equals a repair-free run's.
    plain = _convert(source)
    assert plain.canonical_out is not None
    assert np.array_equal(
        canonical_out.frames[0].atoms.positions,
        plain.canonical_out.frames[0].atoms.positions,
    )


def test_repair_order_is_recorded_in_the_report() -> None:
    source = _poscar_nacl()
    result = _convert(
        source,
        repairs=[
            RepairRequest("identity", {"step": 1}),
            RepairRequest("identity", {"step": 2}),
        ],
    )
    assert result.report.status == "completed"
    assert result.canonical_out is not None
    canonical_out = result.canonical_out
    rows = result.report.repairs
    assert [r.id for r in rows] == ["A1", "A2"]
    assert [r.choice for r in rows] == ["identity", "identity"]
    assert [r.parameters for r in rows] == [{"step": 1}, {"step": 2}]
    # Both applications are recorded in provenance, in order, referencing the same ids.
    history = canonical_out.provenance.history
    repair_records = [r for r in history if r.operation == "repair"]
    assert [r.assumptions for r in repair_records] == [["A1"], ["A2"]]


def test_repair_free_conversion_is_untouched() -> None:
    # A no-repair conversion produces no repair rows/warnings/records and — structurally — no new
    # serialized field (the repairs section is a derived view over `assumptions`).
    result = _convert(_poscar_nacl())
    assert result.report.status == "completed"
    assert result.report.repairs == []
    assert result.report.repair_warnings == []
    assert all(a.scenario != REPAIR_SCENARIO for a in result.report.assumptions)
    assert all(w.source != "repair" for w in result.report.warnings)
    assert result.canonical_out is not None
    assert all(r.operation != "repair" for r in result.canonical_out.provenance.history)
    dumped = result.report.model_dump()
    assert "repairs" not in dumped and "repair_warnings" not in dumped


def test_reproducibility_from_report_alone() -> None:
    """Given the source file and the report, a fresh run re-derives byte-identical output."""
    source_bytes = (GOLDEN / "poscar" / "nacl-primitive" / "POSCAR").read_bytes()
    reg = _registry()

    def run() -> bytes:
        source = _parse(reg, "poscar", GOLDEN / "poscar" / "nacl-primitive" / "POSCAR")
        result = _convert(
            source,
            reg=reg,
            repairs=[RepairRequest("identity", {"step": 7})],
        )
        assert result.output is not None and result.report.status == "completed"
        return result.output

    first = run()

    # Re-derive from the *report* alone: read the recorded operation + complete parameters.
    fresh = _parse(reg, "poscar", GOLDEN / "poscar" / "nacl-primitive" / "POSCAR")
    report = _convert(fresh, reg=reg, repairs=[RepairRequest("identity", {"step": 7})]).report
    (row,) = report.repairs
    assert row.parameters == {"step": 7}
    reparsed = (
        reg.get_parser("poscar")
        .parse(  # a fresh parse of the same file bytes
            io.BytesIO(source_bytes), filename="POSCAR"
        )
        .canonical
    )
    rederived = _convert(
        reparsed,
        reg=reg,
        repairs=[RepairRequest(row.choice, dict(row.parameters))],
    )
    assert rederived.output is not None and rederived.output == first


# --- the recovery-preview seams are repair-aware (v1.7.1 arch review R3; REPAIR-H3) ----------


def _out_of_cell_object() -> CanonicalObject:
    """A single frame in a 4 Å cubic cell with one atom at fractional 1.5 on x (out of cell)."""
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(
                    symbols=["Ar", "Ar"],
                    positions=np.array([[1.0, 1.0, 1.0], [6.0, 1.0, 1.0]], dtype=float),
                ),
                cell=Cell(lattice_vectors=4.0 * np.eye(3), pbc=(True, True, True)),
            )
        ],
        provenance=Provenance(
            source_filename="out-of-cell.poscar",
            source_format="poscar",
            original_coordinate_system="cartesian",
        ),
    )


def _cell_less_object() -> CanonicalObject:
    """A single frame with no cell — a wrap repair on it blocks via ``missing_lattice``."""
    return _out_of_cell_object().model_copy(
        update={
            "frames": [f.model_copy(update={"cell": None}) for f in _out_of_cell_object().frames]
        }
    )


def _preflight_body(report: ConversionReport) -> dict[str, object]:
    """A preflight draft minus its per-call identity (report_id/created_at), for comparison."""
    dumped = report.model_dump(mode="json")
    for volatile in ("report_id", "created_at"):
        dumped.pop(volatile, None)
    return dumped


def test_preflight_reflects_a_clean_repair() -> None:
    # An out-of-cell atom: preflight WITHOUT repairs sees the raw geometry; WITH a wrap repair it
    # sees the wrapped geometry (the pause draft must describe the bytes the resume converts).
    engine = ConversionEngine(_registry())
    source = _out_of_cell_object()
    plain = engine.preflight(source, source_format_id="poscar", target_format_id="xyz")
    wrapped = engine.preflight(
        source,
        source_format_id="poscar",
        target_format_id="xyz",
        repairs=[RepairRequest("wrap_into_cell")],
    )
    # Both are structurally valid drafts.
    assert plain.status == "completed"
    assert wrapped.status == "completed"
    # The repaired draft is exactly the draft of the already-repaired object: the seam applies
    # the repairs before building the diff (nothing is dropped or re-ordered).
    repaired = apply_repairs(source, [RepairRequest("wrap_into_cell")]).canonical
    assert repaired is not None
    prewrapped = engine.preflight(repaired, source_format_id="poscar", target_format_id="xyz")
    assert _preflight_body(wrapped) == _preflight_body(prewrapped)


def test_preflight_repairs_none_is_byte_identical_to_no_repairs() -> None:
    engine = ConversionEngine(_registry())
    source = _out_of_cell_object()
    a = engine.preflight(source, source_format_id="poscar", target_format_id="xyz")
    b = engine.preflight(source, source_format_id="poscar", target_format_id="xyz", repairs=None)
    assert _preflight_body(a) == _preflight_body(b)


def test_preview_recovery_reflects_a_clean_repair() -> None:
    engine = ConversionEngine(_registry())
    source = _out_of_cell_object()
    preview = engine.preview_recovery(
        source,
        source_format_id="poscar",
        target_format_id="xyz",
        repairs=[RepairRequest("wrap_into_cell")],
    )
    assert preview is not None  # a preview never refuses; it previews the repaired object
    assert preview.assumptions == []
    assert preview.unresolved == []


def test_preview_recovery_falls_back_when_a_repair_blocks() -> None:
    # A cell-less object + a wrap that would block on missing_lattice: the PREVIEW must not raise —
    # it falls back to the un-repaired object (the pause is already asking for the lattice).
    engine = ConversionEngine(_registry())
    source = _cell_less_object()
    preview = engine.preview_recovery(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        repairs=[RepairRequest("wrap_into_cell")],
    )
    assert preview is not None  # did not raise
    assert any(u.scenario == "missing_lattice" for u in preview.unresolved)
