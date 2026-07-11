"""Information Discovery Engine tests (M6, MASTER_SPEC Part 3 §6.2–§6.3).

Reproduces the §6.3 worked example (`water_traj.xyz` → the ✓/✗ inventory) and pins the load-
bearing guarantees: the `fields` list is complete over the 16 canonical leaf paths (no absent
path silently omitted), each carries the detected format's *read* capability, carried-through
comments land in `extras` not `fields`, and an undetermined format raises `ParseError`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chembridge.discovery import DiscoveryEngine, DiscoveryReport
from chembridge.registry import default_registry
from chembridge.sdk import CapabilityLevel, ParseError

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = GOLDEN / "xyz" / "water-traj" / "water_traj.xyz"

_LEAF_PATHS = {
    "atoms.symbols",
    "atoms.positions",
    "atoms.masses",
    "frame.time",
    "cell.lattice_vectors",
    "cell.pbc",
    "cell.space_group",
    "trajectory.timestep",
    "dynamics.velocities",
    "dynamics.forces",
    "dynamics.constraints",
    "electronic.total_energy",
    "electronic.stress",
    "electronic.charges",
    "electronic.magnetic_moments",
    "electronic.total_spin",
}


def _discover_water() -> DiscoveryReport:
    engine = DiscoveryEngine(default_registry())
    return engine.discover(WATER.read_bytes(), filename="water_traj.xyz")


def test_worked_example_format_and_structure() -> None:
    report = _discover_water()
    assert report.format["format_id"] == "xyz"
    assert report.format["confidence"] >= 0.5
    # extXYZ scored the file too and is recorded as evidence, never silently dropped.
    assert any(e["format_id"] == "extxyz" for e in report.format["sniff_evidence"])
    assert report.structure == {"frame_count": 2, "atom_count": 3, "species": ["O", "H"]}
    assert report.file["filename"] == "water_traj.xyz"
    assert report.file["size_bytes"] > 0
    assert len(report.file["sha256"]) == 64


def test_fields_are_complete_over_the_leaf_paths() -> None:
    report = _discover_water()
    paths = [f.path for f in report.fields]
    # Every canonical leaf path appears exactly once — "not shown" can never mean "not checked".
    assert set(paths) == _LEAF_PATHS
    assert len(paths) == len(_LEAF_PATHS)


def test_present_and_absent_fields_carry_read_capability() -> None:
    report = _discover_water()
    by_path = {f.path: f for f in report.fields}

    symbols = by_path["atoms.symbols"]
    assert symbols.status == "present"
    assert symbols.format_capability == CapabilityLevel.FULL
    assert symbols.detail == "O, H, H"

    positions = by_path["atoms.positions"]
    assert positions.status == "present"
    assert "2 frame(s) × 3 atoms" in (positions.detail or "")

    # A field the source lacks is reported absent, with the format's read capability for it.
    lattice = by_path["cell.lattice_vectors"]
    assert lattice.status == "absent"
    assert lattice.format_capability == CapabilityLevel.NONE
    assert lattice.detail is None


def test_carried_through_comment_is_an_extra_not_a_field() -> None:
    report = _discover_water()
    field_paths = {f.path for f in report.fields}
    assert "user_metadata.custom_per_frame['xyz:comment']" not in field_paths
    assert "user_metadata.custom_per_frame['xyz:comment']" in report.extras


def test_no_parse_issues_on_clean_file() -> None:
    assert _discover_water().issues == []


def test_format_override_forces_a_parser() -> None:
    report = DiscoveryEngine(default_registry()).discover(
        WATER.read_bytes(), filename="water_traj.xyz", format_override="xyz"
    )
    assert report.format["format_id"] == "xyz"
    assert report.format["overridden"] is True
    # Confidence stays the format's *real* sniff score — an override records the choice, it does
    # not fabricate certainty.
    assert report.format["confidence"] == pytest.approx(0.9)


def test_unknown_format_raises_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        DiscoveryEngine(default_registry()).discover(
            b"\x00\x01 not a chemistry file \xff", filename="x.bin"
        )
    assert any(i.code == "UNKNOWN_FORMAT" for i in exc.value.issues)


def test_mixed_status_lists_present_frames() -> None:
    # A per-frame field present in only some frames must surface as "mixed" with the indices,
    # never collapsed to present/absent (Part 3 §6.2, the trichotomy). Built directly against the
    # field-inventory step, since no v0.1 read format produces a partial-frame field on its own.
    import io

    import numpy as np

    from chembridge.discovery.engine import DiscoveryEngine as _Engine
    from chembridge.schema import Dynamics

    reg = default_registry()
    base = reg.get_parser("xyz").parse(io.BytesIO(WATER.read_bytes()), filename="w.xyz").canonical
    f0 = base.frames[0].model_copy(update={"dynamics": Dynamics(forces=np.zeros((3, 3)))})
    mixed = base.model_copy(update={"frames": [f0, base.frames[1]]})

    entries = _Engine(reg)._fields(mixed, "extxyz")
    forces = next(e for e in entries if e.path == "dynamics.forces")
    assert forces.status == "mixed"
    assert forces.present_frames == [0]
