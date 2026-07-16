"""Regression fixtures for completeness bugs the M10 property test found (Part 8 §1.2).

Property tests find a bug once; goldens keep it found (the M10 plan's rule). These pin the
`frame_selection` × (`constraint_representation` | `missing_lattice`) interactions the stage-2
hypothesis suite surfaced — deterministic reductions of hypothesis-shrunk examples:

* two `constraint_representation` cases that left `dynamics.constraints` in *neither* `preserved`
  nor `removed` — silent loss (**P1**) the runtime completeness invariant caught as a crash;
* the `missing_lattice` × `frame_selection` recovery-detection gap (D51): a `mixed` cell whose
  cell-bearing frame is dropped once crashed the cell-requiring exporter. Recovery now resolves
  `missing_lattice` lazily against the retained frame — fabricate (with a preset), refuse (without),
  or no-op (the retained frame kept a real cell) — and never crashes.
"""

from __future__ import annotations

from typing import Any

import pytest

from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_PRESETS = {
    "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
    "frame_selection": {"choice": "first", "parameters": {}},
    "constraint_representation": {"choice": "drop_all", "parameters": {}},
}


def _object(frame_dynamics: list[dict[str, Any]]) -> CanonicalObject:
    frames = [
        {
            "index": i,
            "atoms": {"symbols": ["H"], "positions": [[0.0, 0.0, 0.0]]},
            "dynamics": dyn,
        }
        for i, dyn in enumerate(frame_dynamics)
    ]
    return CanonicalObject.model_validate(
        {
            "schema_version": "0.1.0",
            "frames": frames,
            "provenance": {
                "source_filename": None,
                "source_format": "extxyz",
                "original_coordinate_system": "cartesian",
            },
        }
    )


@pytest.mark.parametrize("target", ["poscar", "contcar"])
def test_constraints_only_in_dropped_frame_are_reported_removed(target: str) -> None:
    """Constraints present *only* in a frame that ``frame_selection=first`` drops. Before the fix,
    ``constraint_representation`` (running after ``frame_selection`` on the constraint-free retained
    frame) recorded nothing and the constraints path vanished silently."""
    source = _object(
        [
            {},  # frame 0 (retained): no constraints
            {"constraints": [{"kind": "fixed_atoms", "atom_indices": [0], "parameters": {}}]},
        ]
    )
    assert source.field_presence().status_of("dynamics.constraints") == "mixed"

    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id=target,
        mode="permissive",
        recovery_choices=_PRESETS,
    )
    assert result.report.status == "completed"
    removed = {e.path for e in result.report.removed}
    assert "dynamics.constraints" in removed


@pytest.mark.parametrize("target", ["poscar", "contcar"])
def test_empty_constraint_declaration_on_retained_frame_is_reported_removed(target: str) -> None:
    """The retained frame carries an explicitly-unconstrained ``constraints=[]`` (which *is*
    present, §3.6) while the real constraint lived in a dropped frame. ``drop_all`` nulls the empty
    declaration with zero dropped-count; before the fix that present path was recorded nowhere."""
    source = _object(
        [
            {"constraints": []},  # frame 0 (retained): explicitly unconstrained — present, empty
            {"constraints": [{"kind": "fixed_atoms", "atom_indices": [0], "parameters": {}}]},
        ]
    )
    assert source.field_presence().status_of("dynamics.constraints") == "present"

    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id=target,
        mode="permissive",
        recovery_choices=_PRESETS,
    )
    assert result.report.status == "completed"
    removed = {e.path for e in result.report.removed}
    assert "dynamics.constraints" in removed


def test_removed_entries_are_not_duplicated_by_path() -> None:
    """A field a NONE-capability target already routes to ``removed`` and that ``frame_selection``
    also flags (present only in a dropped frame) must appear once, not twice (the dedupe)."""
    source = _object(
        [
            {},  # frame 0 retained: no forces
            {"forces": [[1.0, 0.0, 0.0]]},  # forces only in the dropped frame; POSCAR: NONE cap
        ]
    )
    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id="poscar",
        mode="permissive",
        recovery_choices=_PRESETS,
    )
    paths = [e.path for e in result.report.removed]
    assert paths.count("dynamics.forces") == 1


_LATTICE = {
    "lattice_vectors": [[5.0, 0.0, 0.0], [0.0, 5.0, 0.0], [0.0, 0.0, 5.0]],
    "pbc": [True, True, True],
}


def _object_with_cells(cell_frames: set[int], n_frames: int = 2) -> CanonicalObject:
    """A multi-frame object whose cell is present only in the frames named by ``cell_frames`` — a
    ``mixed`` cell when that is a proper non-empty subset."""
    frames: list[dict[str, Any]] = []
    for i in range(n_frames):
        frame: dict[str, Any] = {
            "index": i,
            "atoms": {"symbols": ["H"], "positions": [[0.0, 0.0, 0.0]]},
            "dynamics": {},
        }
        if i in cell_frames:
            frame["cell"] = dict(_LATTICE)
        frames.append(frame)
    return CanonicalObject.model_validate(
        {
            "schema_version": "0.1.0",
            "frames": frames,
            "provenance": {
                "source_filename": None,
                "source_format": "extxyz",
                "original_coordinate_system": "cartesian",
            },
        }
    )


@pytest.mark.parametrize("target", ["poscar", "contcar"])
def test_mixed_cell_dropped_frame_fabricates_lattice_with_preset(target: str) -> None:
    """The cell lives only in a frame ``frame_selection=first`` drops; the retained frame is
    cell-less. With a ``missing_lattice`` preset the conversion fabricates a lattice for the
    retained frame (D51) and reports it ``supplied`` — before the fix the exporter crashed.

    The fabricated path is reported as the honest **removed + supplied** pair — the dropped source
    cell and its fabricated replacement — and is *not* also ``preserved``: pre-flight optimistically
    predicts a ``mixed`` cell preserved, but the retained frame never carried it, so that prediction
    is struck once recovery fabricates the replacement (D51 report-semantics fix)."""
    source = _object_with_cells({1})  # cell in dropped frame 1 only
    assert source.field_presence().status_of("cell.lattice_vectors") == "mixed"

    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id=target,
        mode="permissive",
        recovery_choices=_PRESETS,
    )
    report = result.report
    assert report.status == "completed"
    preserved = {e.path for e in report.preserved}
    removed = {e.path for e in report.removed}
    supplied = {e.path for e in report.supplied}
    for path in ("cell.lattice_vectors", "cell.pbc"):
        assert path in supplied, f"{path} must be reported supplied (fabricated replacement)"
        assert path in removed, f"{path} must be reported removed (dropped source original)"
        assert path not in preserved, f"{path} must NOT be preserved — it was fabricated, not kept"
    # The retained frame's own genuine data is still preserved (and dropped for the other frame).
    assert "atoms.positions" in preserved and "atoms.positions" in removed
    assert result.validation is not None and result.validation.status == "passed"


@pytest.mark.parametrize("target", ["poscar", "contcar"])
def test_mixed_cell_dropped_frame_refuses_without_preset(target: str) -> None:
    """Same object, but no ``missing_lattice`` preset: the retained frame lacks the required cell,
    so the conversion REFUSES cleanly (honest option list) rather than crashing (D51, req 3)."""
    source = _object_with_cells({1})
    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id=target,
        mode="permissive",
        recovery_choices={"frame_selection": {"choice": "first", "parameters": {}}},
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    unresolved = {s["scenario"] for s in result.report.refusal["unresolved_scenarios"]}
    assert "missing_lattice" in unresolved


@pytest.mark.parametrize("target", ["poscar", "contcar"])
def test_mixed_cell_retained_frame_is_a_noop_no_fabrication(target: str) -> None:
    """The cell lives in the frame ``frame_selection=first`` *keeps*; ``missing_lattice`` is a no-op
    that fabricates nothing and records no Assumption — the real cell is preserved (D51,
    requirement 2). Succeeds without any ``missing_lattice`` preset."""
    source = _object_with_cells({0})  # cell in retained frame 0 only
    result = _ENGINE.convert(
        source,
        source_format_id="extxyz",
        target_format_id=target,
        mode="permissive",
        recovery_choices={"frame_selection": {"choice": "first", "parameters": {}}},
    )
    assert result.report.status == "completed"
    assert "missing_lattice" not in {a.scenario for a in result.report.assumptions}
    assert result.report.supplied == []
    assert result.validation is not None and result.validation.status == "passed"
