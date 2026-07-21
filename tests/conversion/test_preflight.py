"""Pre-flight diff tests (M4, MASTER_SPEC Part 3 §4.3).

The pre-flight diff is the mechanical realization of P5: it must predict *exactly* what a
conversion will preserve, remove, and require — from the source's presence and the target's
declared write capabilities alone, with no per-pair logic.
"""

from __future__ import annotations

import io
from pathlib import Path

from xtalate.capabilities import CapabilityMatrix, Registry
from xtalate.conversion.preflight import build_preflight, capability_path
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


# --- honest, pair-specific option lists on detected scenarios (M7, Part 4 §3.3) ------------------


def test_missing_lattice_scenario_carries_honest_options_excluding_non_periodic() -> None:
    # POSCAR is periodic-only, so the detected scenario's own option list excludes non_periodic —
    # the same list the engine validates against and the refusal report shows (no drift). It does
    # include upload_reference (Slice 2), which any target can offer.
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    diff = build_preflight(source, _matrix(reg), "poscar")
    lattice = next(s for s in diff.unresolved if s.scenario == "missing_lattice")
    assert lattice.options == ["manual_input", "upload_reference", "bounding_box"]
    assert "non_periodic" not in lattice.options


# --- constraint_representation trigger (M7) ------------------------------------------------------

_SELECTIVE_POSCAR = b"""sd test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
2
Selective dynamics
Direct
  0.0 0.0 0.0   T T F
  0.5 0.5 0.5   F F F
"""

_ALL_FREE_POSCAR = b"""all-T test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
1
Selective dynamics
Direct
  0.0 0.0 0.0   T T T
"""


def test_nonempty_constraints_trigger_constraint_representation_not_auto_preserve() -> None:
    # A non-empty constraint list against POSCAR's PARTIAL dynamics.constraints is a recorded choice
    # (Part 4 §3.3) — not auto-preserved, and not in preserved/removed until the resolver decides.
    reg = _registry()
    source = (
        reg.get_parser("poscar").parse(io.BytesIO(_SELECTIVE_POSCAR), filename="POSCAR").canonical
    )
    diff = build_preflight(source, _matrix(reg), "poscar")

    scenario = next(s for s in diff.unresolved if s.scenario == "constraint_representation")
    assert scenario.path == "dynamics.constraints"
    assert scenario.options == ["project", "drop_all"]
    assert scenario.params["representable_kinds"] == ["selective_dynamics"]
    assert "dynamics.constraints" not in {e.path for e in diff.preserved}
    assert "dynamics.constraints" not in {e.path for e in diff.removed}
    assert "dynamics.constraints" not in diff.write_plan


def test_empty_constraints_do_not_trigger_and_preserve_normally() -> None:
    # constraints=[] ("explicitly unconstrained", Part 2 §3.6) carries no subset to choose — it is
    # present and PARTIAL-representable, so it preserves normally, no scenario.
    reg = _registry()
    source = (
        reg.get_parser("poscar").parse(io.BytesIO(_ALL_FREE_POSCAR), filename="POSCAR").canonical
    )
    assert source.frames[0].dynamics.constraints == []
    diff = build_preflight(source, _matrix(reg), "poscar")
    assert [s.scenario for s in diff.unresolved] == []
    assert "dynamics.constraints" in {e.path for e in diff.preserved}


def test_xyz_target_preserves_only_comment_of_custom_per_frame() -> None:
    # Plain XYZ writes one free-text comment line per frame (xyz:comment) and nothing else. An
    # extXYZ source's foreign per-frame key must be predicted Removed — declaring the container
    # FULL would predict it Preserved and then the exporter would silently drop it (Part 3 §4.2).
    # Only the comment (if present) enters the write_plan, and per key, so canonical' keeps just it.
    reg = _registry()
    data = b"1\nProperties=species:S:1:pos:R:3 config_type=slab\nH 0 0 0\n"
    source = reg.get_parser("extxyz").parse(io.BytesIO(data), filename="s.extxyz").canonical
    diff = build_preflight(source, _matrix(reg), "xyz")

    assert "user_metadata.custom_per_frame['extxyz:config_type']" in {e.path for e in diff.removed}
    assert "user_metadata.custom_per_frame['extxyz:config_type']" not in {
        e.path for e in diff.preserved
    }
    assert "user_metadata.custom_per_frame" not in diff.write_plan


def test_xyz_target_keeps_comment_key_per_key_in_write_plan() -> None:
    # A source carrying the free-text comment: xyz:comment is Preserved and enters the write_plan at
    # per-key granularity (not the whole container), so a sibling foreign key would not ride along.
    reg = _registry()
    xyz = b"1\nhello world\nH 0 0 0\n"
    source = reg.get_parser("xyz").parse(io.BytesIO(xyz), filename="t.xyz").canonical
    diff = build_preflight(source, _matrix(reg), "xyz")

    assert "user_metadata.custom_per_frame['xyz:comment']" in {e.path for e in diff.preserved}
    assert "user_metadata.custom_per_frame['xyz:comment']" in diff.write_plan
    assert "user_metadata.custom_per_frame" not in diff.write_plan


# --- pattern-declared writable sets (D69) ----------------------------------------------------


def test_extxyz_target_removes_a_per_atom_key_its_grammar_cannot_spell() -> None:
    # extXYZ's writable per-atom set is open-ended, so it is declared as a *pattern* rather than a
    # list (D69). A CIF source's `cif:occupancy` fails that pattern — the Properties= grammar
    # separates its fields with ':', so the column cannot be written under that name at all. This
    # must be predicted Removed, and the stakes are higher than the usual over-promise: writing it
    # anyway does not merely lose the column, it produces a file ASE cannot re-parse.
    reg = _registry()
    source = _parse(reg, "cif", GOLDEN / "cif" / "zno-hexagonal-p1" / "zno_hexagonal.cif")
    diff = build_preflight(source, _matrix(reg), "extxyz")

    key = "user_metadata.custom_per_atom['cif:occupancy']"
    removed = {e.path: e for e in diff.removed}
    assert key in removed
    assert key not in {e.path for e in diff.preserved}
    assert key not in diff.write_plan
    # The reason names the pattern, so a user reading the report can see *why* this key and not
    # some blanket "extXYZ drops custom columns" claim, which would be false.
    assert "extxyz:" in removed[key].reason


def test_extxyz_target_preserves_a_per_atom_key_that_matches_the_pattern() -> None:
    # The other half: a key extXYZ *can* spell is Preserved and enters the write_plan per key, the
    # same granularity a list-declared container gets. The extXYZ parser prefixes every column it
    # reads, so a source column `tag` arrives canonically as `extxyz:tag` — which is exactly the
    # shape the pattern admits, and is why the pattern is `extxyz:<name>` and not merely "no colon".
    reg = _registry()
    data = b"1\nProperties=species:S:1:pos:R:3:tag:S:1\nH 0 0 0 core\n"
    source = reg.get_parser("extxyz").parse(io.BytesIO(data), filename="s.extxyz").canonical
    assert "extxyz:tag" in source.user_metadata.custom_per_atom

    diff = build_preflight(source, _matrix(reg), "extxyz")
    key = "user_metadata.custom_per_atom['extxyz:tag']"
    assert key in {e.path for e in diff.preserved}
    assert key in diff.write_plan
    assert "user_metadata.custom_per_atom" not in diff.write_plan


def test_ase_traj_target_removes_every_per_atom_key_regardless_of_name() -> None:
    # ASE's .traj writer persists no custom per-atom array under any name, so it gets no pattern —
    # it declares the container NONE (D69). Verified through the whole container, not one key.
    reg = _registry()
    source = _parse(reg, "cif", GOLDEN / "cif" / "zno-hexagonal-p1" / "zno_hexagonal.cif")
    diff = build_preflight(source, _matrix(reg), "ase_traj")

    per_atom = {
        f"user_metadata.custom_per_atom['{k}']" for k in source.user_metadata.custom_per_atom
    }
    assert per_atom  # the fixture must actually carry columns, or this proves nothing
    assert per_atom <= {e.path for e in diff.removed}
    assert not (per_atom & diff.write_plan)
