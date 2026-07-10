"""Pre-flight diff tests (M4, MASTER_SPEC Part 3 §4.3).

The pre-flight diff is the mechanical realization of P5: it must predict *exactly* what a
conversion will preserve, remove, and require — from the source's presence and the target's
declared write capabilities alone, with no per-pair logic.
"""

from __future__ import annotations

import io
from pathlib import Path

from chembridge.capabilities import CapabilityMatrix, Registry
from chembridge.conversion.preflight import build_preflight, capability_path
from chembridge.exporters import builtin_exporters
from chembridge.parsers import builtin_parsers
from chembridge.schema import CanonicalObject

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


def _matrix(reg: Registry) -> CapabilityMatrix:
    return reg.capability_matrix()


def test_capability_path_strips_dynamic_custom_key() -> None:
    assert capability_path("user_metadata.custom_per_frame['xyz:comment']") == (
        "user_metadata.custom_per_frame"
    )
    assert capability_path("cell.lattice_vectors") == "cell.lattice_vectors"


def test_extxyz_to_poscar_predicts_exact_diff() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    diff = build_preflight(source, _matrix(reg), "poscar")

    assert {e.path for e in diff.preserved} == {
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
        "cell.pbc",
    }
    assert {e.path for e in diff.removed} == {
        "atoms.masses",
        "dynamics.forces",
        "electronic.total_energy",
        "electronic.charges",
        "user_metadata.custom_per_frame['extxyz:config_type']",
    }
    # cell.pbc is PARTIAL for POSCAR → preserved but its condition surfaced as a warning.
    assert any(w.code == "PARTIAL_CAPABILITY" for w in diff.warnings)
    assert any(w.code == "FORMAT_LOSSY_NOTE" for w in diff.warnings)
    assert diff.write_plan == {
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
        "cell.pbc",
    }
    assert diff.unresolved == []


def test_every_removed_entry_carries_a_reason() -> None:
    reg = _registry()
    source = _parse(reg, "extxyz", GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
    diff = build_preflight(source, _matrix(reg), "poscar")
    assert all(e.reason for e in diff.removed)


def test_xyz_multiframe_to_poscar_detects_both_recovery_triggers() -> None:
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    diff = build_preflight(source, _matrix(reg), "poscar")

    # frame_selection is ordered before missing_lattice — a bounding box is computed on the
    # chosen frame (the dependency of Part 4 §3.3).
    assert [s.scenario for s in diff.unresolved] == ["frame_selection", "missing_lattice"]
    lattice = next(s for s in diff.unresolved if s.scenario == "missing_lattice")
    assert lattice.path == "cell.lattice_vectors"


def test_derived_atomic_numbers_excluded_from_diff() -> None:
    # atoms.atomic_numbers is a derived mirror of symbols, never an independent loss.
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    diff = build_preflight(source, _matrix(reg), "poscar")
    all_paths = {e.path for e in diff.preserved} | {e.path for e in diff.removed}
    assert "atoms.atomic_numbers" not in all_paths


def test_single_frame_xyz_to_poscar_only_needs_lattice() -> None:
    reg = _registry()
    data = b"1\nlone O\nO 0.0 0.0 0.0\n"
    source = reg.get_parser("xyz").parse(io.BytesIO(data), filename="o.xyz").canonical
    diff = build_preflight(source, _matrix(reg), "poscar")
    assert [s.scenario for s in diff.unresolved] == ["missing_lattice"]
