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


def test_poscar_to_poscar_passes_validation() -> None:
    # Identity conversion. The scaling factor is a provenance note, not a simulation.extra field
    # (D34) — storing it there made this false-fail absence-conformance, since the re-parse always
    # re-derives a scale but no exporter carries simulation.*.
    reg = _registry()
    source = _parse(reg, "poscar", GOLDEN / "poscar" / "nacl-primitive" / "POSCAR")
    result = ConversionEngine(reg).convert(
        source, source_format_id="poscar", target_format_id="poscar", source_filename="POSCAR"
    )
    assert result.report.status == "completed"
    assert result.validation is not None
    assert result.validation.status == "passed"


def test_interleaved_species_to_poscar_passes_validation() -> None:
    # H O H → POSCAR reorders to H H O. The exporter's atom_permutation lets validation compare
    # under that grouping; without it species_preservation/positions_rmsd false-fail.
    reg = _registry()
    source = (
        reg.get_parser("xyz")
        .parse(io.BytesIO(b"3\nwater-ish\nH 0 0 0\nO 0 0 1\nH 0 1 1\n"), filename="t.xyz")
        .canonical
    )
    result = ConversionEngine(reg).convert(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices={
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}
        },
    )
    assert result.report.status == "completed"
    assert result.validation is not None
    assert result.validation.status == "passed"
    species = [c for c in result.validation.checks if c.check_id == "species_preservation"]
    assert species and species[0].status == "pass"


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


# --- constraint_representation end to end (M7, Part 4 §3.3) ---------------------------------------

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


def _selective_source(reg: Registry) -> CanonicalObject:
    return (
        reg.get_parser("poscar").parse(io.BytesIO(_SELECTIVE_POSCAR), filename="POSCAR").canonical
    )


def test_constraint_poscar_to_poscar_refuses_without_a_preset() -> None:
    # A partial constraint translation changes downstream physics, so POSCAR→POSCAR with a
    # non-empty selective_dynamics block now *refuses* without an explicit choice (Part 4 §3.3),
    # and the refusal carries the honest option list (P5).
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _selective_source(reg), source_format_id="poscar", target_format_id="poscar"
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    (scenario,) = result.report.refusal["unresolved_scenarios"]
    assert scenario["scenario"] == "constraint_representation"
    assert scenario["options"] == ["project", "drop_all"]


def test_constraint_project_completes_and_preserves_the_kept_subset() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _selective_source(reg),
        source_format_id="poscar",
        target_format_id="poscar",
        recovery_choices={"constraint_representation": {"choice": "project"}},
    )
    assert result.report.status == "completed"
    # The retained constraint is Preserved (genuine data), never Supplied (P4).
    assert "dynamics.constraints" in {e.path for e in result.report.preserved}
    assert "dynamics.constraints" not in {e.path for e in result.report.supplied}
    (assumption,) = result.report.assumptions
    assert assumption.scenario == "constraint_representation"
    assert assumption.choice == "project"
    assert result.validation is not None
    assert result.validation.status in ("passed", "passed_with_warnings")


def test_constraint_drop_all_completes_and_removes_the_constraints() -> None:
    reg = _registry()
    result = ConversionEngine(reg).convert(
        _selective_source(reg),
        source_format_id="poscar",
        target_format_id="poscar",
        recovery_choices={"constraint_representation": {"choice": "drop_all"}},
    )
    assert result.report.status == "completed"
    assert "dynamics.constraints" in {e.path for e in result.report.removed}
    assert result.report.supplied == []
    assert result.canonical_out is not None
    assert result.canonical_out.frames[0].dynamics.constraints is None


# --- frame_selection=split_all end to end (Slice 2, Part 4 §3.3) ---------------------------------


def test_split_all_writes_one_output_per_frame_and_validates_each() -> None:
    # A 2-frame XYZ trajectory → POSCAR with split_all: `output` is None, `outputs` carries one
    # single-structure file per frame, and the merged validation covers every file.
    reg = _registry()
    source = _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
    n = source.frame_count
    result = ConversionEngine(reg).convert(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices={
            "frame_selection": {"choice": "split_all"},
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 2.0}},
        },
    )
    assert result.report.status == "completed"
    assert result.output is None
    assert result.outputs is not None and len(result.outputs) == n
    # Each split file re-parses as a single-structure POSCAR.
    for chunk in result.outputs:
        assert reg.get_parser("poscar").parse(io.BytesIO(chunk), filename="POSCAR").canonical
    # One frame_selection Assumption for the split (no per-frame Assumptions).
    assert [a.choice for a in result.report.assumptions if a.scenario == "frame_selection"] == [
        "split_all"
    ]
    assert result.validation is not None
    assert result.validation.status in ("passed", "passed_with_warnings")
    # Merged validation tags each check with the file it came from.
    assert {c.measured.get("split_file_index") for c in result.validation.checks} == set(range(n))


def test_upload_reference_lattice_end_to_end() -> None:
    # A no-lattice single-frame XYZ borrows its POSCAR lattice from a matching reference structure.
    reg = _registry()
    xyz = b"2\nf\nH 0 0 0\nH 0 0 0.8\n"
    source = reg.get_parser("xyz").parse(io.BytesIO(xyz), filename="t.xyz").canonical
    ref_poscar = b"ref\n1.0\n 5 0 0\n 0 5 0\n 0 0 5\nH\n2\nDirect\n 0 0 0\n 0.1 0.1 0.1\n"
    reference = reg.get_parser("poscar").parse(io.BytesIO(ref_poscar), filename="POSCAR").canonical
    result = ConversionEngine(reg).convert(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices={
            "missing_lattice": {
                "choice": "upload_reference",
                "parameters": {"reference": reference},
            }
        },
    )
    assert result.report.status == "completed"
    assert "cell.lattice_vectors" in {s.path for s in result.report.supplied}
    assert result.validation is not None and result.validation.status in (
        "passed",
        "passed_with_warnings",
    )


def test_xyz_comments_to_extxyz_validates_passed() -> None:
    # Regression: an XYZ source carrying per-frame comments (user_metadata.custom_per_frame
    # ['xyz:comment']) → extXYZ. The comment key must round-trip verbatim (not become
    # extxyz:xyz:comment), or metadata_preservation false-fails though the value survives.
    reg = _registry()
    xyz = b"2\nframe zero\nH 0 0 0\nH 0 0 0.8\n2\nframe one\nH 0 0 0\nH 0 0 0.9\n"
    source = reg.get_parser("xyz").parse(io.BytesIO(xyz), filename="t.xyz").canonical
    result = ConversionEngine(reg).convert(
        source, source_format_id="xyz", target_format_id="extxyz"
    )
    assert result.report.status == "completed"
    assert "user_metadata.custom_per_frame['xyz:comment']" in {
        e.path for e in result.report.preserved
    }
    assert result.validation is not None
    assert result.validation.status in ("passed", "passed_with_warnings")


def test_extxyz_foreign_per_frame_key_to_xyz_is_removed_not_false_failed() -> None:
    # Sibling of the above, the other direction: extXYZ → plain XYZ. Plain XYZ holds only its
    # free-text comment (xyz:comment), so a foreign per-frame key (config_type) cannot be expressed.
    # It must be reported *removed* and dropped from canonical′ — declaring the container FULL would
    # predict it Preserved, the exporter would silently drop it, and metadata_preservation would
    # false-fail (Part 3 §4.2). The conversion completes and validates.
    reg = _registry()
    data = b"1\nProperties=species:S:1:pos:R:3 config_type=slab\nH 0 0 0\n"
    source = reg.get_parser("extxyz").parse(io.BytesIO(data), filename="s.extxyz").canonical
    result = ConversionEngine(reg).convert(
        source, source_format_id="extxyz", target_format_id="xyz"
    )
    assert result.report.status == "completed"
    removed = {e.path for e in result.report.removed}
    assert "user_metadata.custom_per_frame['extxyz:config_type']" in removed
    assert result.canonical_out is not None
    assert result.canonical_out.user_metadata.custom_per_frame == {}
    assert result.validation is not None
    assert result.validation.status == "passed"


def test_xyz_with_comment_to_xyz_still_preserves_the_comment() -> None:
    # The restriction must not regress the comment round-trip: xyz → xyz keeps xyz:comment.
    reg = _registry()
    xyz = b"1\nframe zero\nH 0 0 0\n1\nframe one\nH 0 0 0.8\n"
    source = reg.get_parser("xyz").parse(io.BytesIO(xyz), filename="t.xyz").canonical
    result = ConversionEngine(reg).convert(source, source_format_id="xyz", target_format_id="xyz")
    assert result.report.status == "completed"
    assert result.validation is not None
    assert result.validation.status == "passed"
    assert result.canonical_out is not None
    assert result.canonical_out.user_metadata.custom_per_frame == {
        "xyz:comment": ["frame zero", "frame one"]
    }


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


# --- CIF as a recovery-requiring target (v0.4 review, tier 5.2) --------------------------------
#
# CIF declares `cell.lattice_vectors` in `required_fields`, so the pre-flight maps it to the
# `missing_lattice` scenario exactly as POSCAR and XDATCAR do — by declaration, with no CIF-shaped
# special case anywhere in the recovery layer. Nothing under tests/recovery/ or tests/conversion/
# named CIF, so that generic wiring was true only by inspection. These pin both halves of the
# bright line for the format v0.4 added: refusal without a preset, fabrication *recorded* with one.


def _lattice_less_source(reg: Registry) -> CanonicalObject:
    # Plain XYZ carries no cell at all — the honest single-frame source for this gap.
    return _parse(reg, "xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")


def test_a_cell_less_source_to_cif_is_refused_without_a_preset() -> None:
    # P4: a CIF cannot be written without a cell, and inventing one nobody asked for is the silent
    # fabrication the Recovery Engine exists to prevent. Refusal is the default, not an error.
    reg = _registry()
    source = _lattice_less_source(reg)
    result = ConversionEngine(reg).convert(
        source,
        source_format_id="xyz",
        target_format_id="cif",
        source_filename="water_traj.xyz",
        recovery_choices={"frame_selection": {"choice": "first"}},
    )
    assert result.report.status == "refused"
    refusal = result.report.refusal
    assert refusal is not None
    assert refusal["code"] == "RECOVERY_REQUIRED"
    unresolved = refusal["unresolved_scenarios"]
    assert {u["scenario"] for u in unresolved} == {"missing_lattice"}
    # The refusal names the choices available, so the user can act on it without reading source.
    assert "bounding_box" in unresolved[0]["options"]


def test_a_fabricated_cell_reaches_cif_and_is_recorded_as_supplied() -> None:
    # With the choice made explicitly, the conversion completes — and the fabrication is *audited*:
    # an Assumption records it, `supplied` names the path, and the artifact is a real CIF. A
    # fabricated cell that reached the file without either record would be the failure P4 names.
    reg = _registry()
    source = _lattice_less_source(reg)
    result = ConversionEngine(reg).convert(
        source,
        source_format_id="xyz",
        target_format_id="cif",
        source_filename="water_traj.xyz",
        recovery_choices={
            "frame_selection": {"choice": "first"},
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
        },
    )
    assert result.report.status == "completed"
    assert "cell.lattice_vectors" in {s.path for s in result.report.supplied}
    assert any(a.scenario == "missing_lattice" for a in result.report.assumptions)
    assert result.output is not None and result.output.startswith(b"data_")
    assert result.validation is not None and result.validation.status == "passed"
