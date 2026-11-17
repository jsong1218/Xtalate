"""ConversionEngine.dry_run — parse + repairs + pre-flight, never writes (QoL Q2)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from xtalate.capabilities import Registry
from xtalate.conversion.engine import ConversionEngine, DryRun
from xtalate.registry import default_registry
from xtalate.repair import RepairError, RepairRequest
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = GOLDEN / "xyz" / "water-traj" / "water_traj.xyz"  # 2 frames, no cell
CO_IN_CELL = GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz"  # 1 frame, with a cell


def _parse(path: Path, fmt: str) -> tuple[Registry, CanonicalObject]:
    registry = default_registry()
    result = registry.get_parser(fmt).parse(io.BytesIO(path.read_bytes()), filename=path.name)
    return registry, result.canonical


def _dry(
    registry: Registry,
    obj: CanonicalObject,
    source_format: str,
    target: str,
    repairs: list[RepairRequest] | None = None,
) -> DryRun:
    return ConversionEngine(registry).dry_run(
        obj,
        source_format_id=source_format,
        target_format_id=target,
        source_filename="in",
        target_filename="out",
        mode="permissive",
        repairs=repairs,
    )


def test_complete_conversion_is_completed_with_no_unresolved() -> None:
    registry, obj = _parse(CO_IN_CELL, "extxyz")
    result = _dry(registry, obj, "extxyz", "poscar")
    assert result.report.stage == "preflight"
    assert result.report.status == "completed"
    assert result.report.refusal is None
    assert result.unresolved == []
    assert result.blocked == []


def test_needs_recovery_reports_awaiting_recovery_with_scenarios() -> None:
    registry, obj = _parse(WATER, "xyz")
    result = _dry(registry, obj, "xyz", "poscar")
    assert result.report.status == "awaiting_recovery"
    names = {u.scenario for u in result.unresolved}
    assert {"missing_lattice", "frame_selection"} <= names
    body = result.report.refusal
    assert body is not None and body["code"] == "RECOVERY_REQUIRED"
    assert {s["scenario"] for s in body["unresolved_scenarios"]} == names


def test_repairs_are_applied_strictly_and_listed() -> None:
    registry, obj = _parse(WATER, "xyz")
    result = _dry(
        registry,
        obj,
        "xyz",
        "extxyz",
        repairs=[RepairRequest(operation="select_frames", parameters={"start": 0, "stop": 1})],
    )
    assert [a.operation for a in result.applied] == ["select_frames"]
    assert result.applied[0].description.startswith("Kept frames 0:1:1 (1 of 2)")
    assert result.report.status == "completed"


def test_repair_that_resolves_a_need_removes_it_from_the_unresolved_set() -> None:
    registry, obj = _parse(WATER, "xyz")
    result = _dry(
        registry,
        obj,
        "xyz",
        "poscar",
        repairs=[RepairRequest(operation="select_frames", parameters={"start": 0, "stop": 1})],
    )
    # One frame left, so frame_selection is no longer needed; the lattice still is.
    assert {u.scenario for u in result.unresolved} == {"missing_lattice"}


def test_blocked_repair_surfaces_as_awaiting_recovery_not_swallowed() -> None:
    registry, obj = _parse(WATER, "xyz")
    # wrap_into_cell on a cell-less object blocks; the block maps onto missing_lattice.
    result = _dry(
        registry, obj, "xyz", "extxyz", repairs=[RepairRequest(operation="wrap_into_cell")]
    )
    assert [b.operation for b in result.blocked] == ["wrap_into_cell"]
    assert result.report.status == "awaiting_recovery"
    assert any(u.scenario == "missing_lattice" for u in result.unresolved)
    assert result.report.refusal is not None
    assert "wrap_into_cell" in result.report.refusal["message"]


def test_empty_selection_raises_repair_error() -> None:
    registry, obj = _parse(WATER, "xyz")
    with pytest.raises(RepairError, match="selects no frames"):
        _dry(
            registry,
            obj,
            "xyz",
            "extxyz",
            repairs=[RepairRequest(operation="select_frames", parameters={"start": 5, "stop": 9})],
        )


def test_dry_run_does_not_mutate_the_source_object() -> None:
    registry, obj = _parse(WATER, "xyz")
    before = obj.model_dump(mode="json")
    _dry(
        registry,
        obj,
        "xyz",
        "extxyz",
        repairs=[RepairRequest(operation="select_frames", parameters={"stop": 1})],
    )
    assert obj.model_dump(mode="json") == before
    assert obj.frame_count == 2
