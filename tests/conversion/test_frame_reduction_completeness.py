"""Regression fixtures for completeness bugs the M10 property test found (Part 8 §1.2).

Property tests find a bug once; goldens keep it found (the M10 plan's rule). These pin two
`frame_selection` × `constraint_representation` interactions that left `dynamics.constraints` in
*neither* `preserved` nor `removed` — silent loss (**P1**) the runtime completeness invariant caught
as a crash. Both are deterministic reductions of hypothesis-shrunk examples.
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
