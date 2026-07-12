"""Conversion Engine tests (M4, MASTER_SPEC Part 4 §1–2).

Covers the happy path (a full conversion whose final report satisfies the completeness
invariant and whose output re-parses), the write_plan discipline (the exporter receives
exactly the plan as a filtered object), the structured refusal (a recovery-needing conversion
is a completed `refused` outcome, not an error), and the completeness invariant itself firing
on a tampered report.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests._format_helpers import assert_scientifically_equal
from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.conversion.engine import CompletenessInvariantError, _assert_completeness
from xtalate.conversion.report import PreservedEntry, SuppliedEntry
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def _parse(reg: Registry, format_id: str, path: Path) -> CanonicalObject:
    return (
        reg.get_parser(format_id).parse(io.BytesIO(path.read_bytes()), filename=path.name).canonical
    )


# --- happy path -----------------------------------------------------------------------


def test_extxyz_to_poscar_completes_and_output_reparses() -> None:
    reg = _registry()
    engine = ConversionEngine(reg)
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    result = engine.convert(
        source, source_format_id="extxyz", target_format_id="poscar", source_filename="s.extxyz"
    )

    assert result.report.status == "completed"
    assert result.report.stage == "final"
    assert result.output is not None
    # The predicted-preserved fields actually survive a re-parse of the written POSCAR.
    reparsed = (
        reg.get_parser("poscar").parse(io.BytesIO(result.output), filename="POSCAR").canonical
    )
    assert reparsed.frames[0].atoms.symbols == source.frames[0].atoms.symbols
    assert reparsed.frames[0].cell is not None


def test_final_report_has_convert_provenance_record() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    result = ConversionEngine(reg).convert(
        source, source_format_id="extxyz", target_format_id="poscar"
    )
    assert result.canonical_out is not None
    last = result.canonical_out.provenance.history[-1]
    assert last.operation == "convert"
    assert last.target_format == "poscar"
    assert last.source_format == "extxyz"


# --- write_plan discipline (Part 4 §1) ------------------------------------------------


def test_write_plan_nulls_excluded_fields_in_canonical_out() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    result = ConversionEngine(reg).convert(
        source, source_format_id="extxyz", target_format_id="poscar"
    )
    out = result.canonical_out
    assert out is not None
    frame = out.frames[0]
    # POSCAR cannot store these → the exporter must never see them (they are None on canonical′).
    assert frame.atoms.masses is None
    assert frame.dynamics.forces is None
    assert frame.electronic.total_energy is None
    assert frame.electronic.charges is None
    assert out.user_metadata.custom_per_frame == {}
    # POSCAR *can* store these → kept.
    assert frame.cell is not None
    assert frame.atoms.symbols == source.frames[0].atoms.symbols


def test_canonical_out_positions_unchanged_by_filtering() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    result = ConversionEngine(reg).convert(
        source, source_format_id="extxyz", target_format_id="poscar"
    )
    assert result.canonical_out is not None
    import numpy as np

    assert np.array_equal(
        result.canonical_out.frames[0].atoms.positions, source.frames[0].atoms.positions
    )


# --- structured refusal (Part 4 §4) ---------------------------------------------------


def test_xyz_multiframe_to_poscar_is_refused_not_errored() -> None:
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    result = ConversionEngine(reg).convert(
        source, source_format_id="xyz", target_format_id="poscar"
    )

    assert result.report.status == "refused"
    assert result.output is None
    assert result.canonical_out is None
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = [s["scenario"] for s in result.report.refusal["unresolved_scenarios"]]
    assert scenarios == ["frame_selection", "missing_lattice"]
    # A refused report still carries the full loss prediction (Part 4 §4).
    assert {e.path for e in result.report.preserved} >= {"atoms.symbols", "atoms.positions"}


def test_preflight_is_awaiting_recovery_when_scenarios_unresolved() -> None:
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    report = ConversionEngine(reg).preflight(
        source, source_format_id="xyz", target_format_id="poscar"
    )
    assert report.stage == "preflight"
    assert report.status == "awaiting_recovery"


# --- completeness invariant (review §4.5) ---------------------------------------------


def _report_stub() -> ConversionReport:
    return ConversionReport(
        report_id="r",
        stage="final",
        status="completed",
        mode="permissive",
        created_at="2026-01-01T00:00:00Z",
        source={"format_id": "xyz"},
        target={"format_id": "poscar"},
    )


def test_completeness_invariant_fires_on_unaccounted_present_path() -> None:
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    report = _report_stub()  # accounts for nothing, though the source has present fields
    with pytest.raises(CompletenessInvariantError, match="silent loss"):
        _assert_completeness(report, source)


def test_completeness_invariant_fires_on_supplied_that_was_present() -> None:
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    report = _report_stub()
    # Account for every present path so only the supplied check can fail.
    report.preserved = [PreservedEntry(path=p) for p in source.field_presence().present_paths()]
    report.supplied = [SuppliedEntry(path="atoms.positions", from_assumption="A1")]
    with pytest.raises(CompletenessInvariantError, match="silent fabrication"):
        _assert_completeness(report, source)


def test_identity_conversion_preserves_everything() -> None:
    # extXYZ → extXYZ: the target can express everything the source holds, so nothing is
    # removed and the round-tripped object equals the source's scientific content.
    reg = _registry()
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    result = ConversionEngine(reg).convert(
        source, source_format_id="extxyz", target_format_id="extxyz"
    )
    assert result.report.status == "completed"
    assert result.report.removed == []
    assert result.output is not None
    reparsed = reg.get_parser("extxyz").parse(io.BytesIO(result.output), filename=None).canonical
    assert_scientifically_equal(source, reparsed)
