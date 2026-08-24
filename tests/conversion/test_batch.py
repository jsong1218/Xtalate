"""Batch conversion tests (v1.5 M54-S1, MASTER_SPEC Part 6 preamble aggregation rule).

The batch surface is a **wrapper** — the plan's design-critical claim is that the aggregate
embeds the existing report models verbatim and that one file's failure never aborts the batch.
These tests pin exactly that: correct tallies over a mixed manifest (clean + refusing + corrupt),
**byte-identical** embedding (same file converted alone vs. inside the batch), deterministic
globs and report ordering, the opt-in ``fail_fast``, and the manifest-error surface (a caller
mistake is a clean error, never a partial run). Selection/split/dedup keys are rejected by the
model's ``extra="forbid"`` (the scope refusal, enforced not merely omitted).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from xtalate.capabilities import Registry
from xtalate.conversion import (
    BatchManifest,
    BatchManifestError,
    ConversionEngine,
    SourceEntry,
    SourceOverride,
    load_manifest,
    parse_with_recovery,
    run_batch,
)
from xtalate.conversion.batch import RecoveryPresetError
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = GOLDEN / "xyz" / "water-traj" / "water_traj.xyz"
CO_IN_CELL = GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz"
MLIP = GOLDEN / "extxyz" / "mlip-labeled-2frame" / "mlip_labeled.extxyz"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def _corrupt(tmp_path: Path) -> Path:
    junk = tmp_path / "junk.bin"
    junk.write_text("this is not a chemistry file at all\n")
    return junk


def _norm(report: dict[str, Any]) -> dict[str, Any]:
    """Normalise the run-varying identifiers (the streamed==materialized precedent): a fresh
    UUID is minted per report, and a ValidationReport links to *its* ConversionReport by id, so
    the two runs' ids differ by construction — the substantive content is what must match."""
    report = json.loads(json.dumps(report))
    report["report_id"] = "X"
    report["created_at"] = "X"
    if "conversion_report_id" in report:
        report["conversion_report_id"] = "X"
    return report


# --- failure isolation + tallies (done-means 1) ----------------------------------------------


def test_mixed_manifest_isolates_failures_and_tallies_correctly(tmp_path: Path) -> None:
    # One clean file, one refusal (a stress carry needs a convention preset — data-dependent
    # recovery), one corrupt file (an unparseable blob): no file's failure aborts the batch.
    junk = _corrupt(tmp_path)
    report = run_batch(
        BatchManifest(
            sources=[str(WATER), str(MLIP), str(junk)],
            target="extxyz",
        ),
        _registry(),
    )
    assert report.tallies.model_dump() == {
        "total": 3,
        "converted": 1,
        "refused": 1,
        "failed": 1,
        "label_presence": {"energy": 0, "forces": 0, "stress": 0},
    }
    # Manifest order is processing order **and** report order.
    assert [e.source for e in report.entries] == [str(WATER), str(MLIP), str(junk)]
    clean, refused, failed = report.entries
    assert clean.status == "converted"
    assert clean.conversion is not None and clean.conversion.status == "completed"
    assert clean.validation is not None and clean.validation.status == "passed"
    assert refused.status == "refused"
    assert refused.conversion is not None and refused.conversion.status == "refused"
    assert refused.conversion.refusal is not None
    assert refused.conversion.refusal["code"] == "RECOVERY_REQUIRED"
    assert failed.status == "failed"
    assert failed.conversion is None  # no conversion could start: no report to embed
    assert failed.error is not None and failed.error.code == "UNKNOWN_FORMAT"


def test_label_presence_counts_derived_from_per_file_objects() -> None:
    # co-in-cell carries energy + forces; plain water carries none. Counts derive from the
    # per-file reports' preserved paths (what the target actually wrote), never a restatement.
    report = run_batch(
        BatchManifest(sources=[str(WATER), str(CO_IN_CELL)], target="extxyz"),
        _registry(),
    )
    assert report.tallies.total == 2
    assert report.tallies.converted == 2
    assert report.tallies.label_presence.model_dump() == {
        "energy": 1,
        "forces": 1,
        "stress": 0,
    }


# --- structural honesty: verbatim embedding (done-means 2) ------------------------------------


def test_embedded_report_is_byte_identical_to_standalone_conversion() -> None:
    # The same file converted alone and inside a batch serializes byte-identically — the
    # machine-checkable form of "the aggregate cannot elide a per-file loss" (P1 at dataset
    # scale). The batch entry *is* the same ConversionReport/ValidationReport instances.
    reg = _registry()
    report = run_batch(BatchManifest(sources=[str(WATER)], target="extxyz"), reg)
    (entry,) = report.entries
    assert entry.status == "converted"

    data = WATER.read_bytes()
    parsed = parse_with_recovery(reg, data, filename=WATER.name)
    standalone = ConversionEngine(reg).convert(
        parsed.canonical,
        source_format_id=parsed.format_id,
        target_format_id="extxyz",
        source_filename=WATER.name,
        target_filename="water_traj.extxyz",
        parse_recovery=parsed,
    )
    assert entry.conversion is not None
    assert _norm(entry.conversion.model_dump(mode="json")) == _norm(
        standalone.report.model_dump(mode="json")
    )
    assert entry.validation is not None and standalone.validation is not None
    assert _norm(entry.validation.model_dump(mode="json")) == _norm(
        standalone.validation.model_dump(mode="json")
    )


# --- determinism + glob resolution (done-means 3) ---------------------------------------------


def _paths(sources: list[SourceEntry | str]) -> list[str]:
    """The manifest's concrete source paths (a source is a literal path or a glob pattern)."""
    return [s.path if isinstance(s, SourceEntry) else s for s in sources]


def test_glob_resolution_is_deterministic_and_recorded() -> None:
    pattern = str(GOLDEN / "extxyz" / "*" / "*.extxyz")
    manifest = BatchManifest(sources=[pattern], target="extxyz")
    reg = _registry()
    first = run_batch(manifest, reg)
    second = run_batch(manifest, reg)
    # The resolved list is recorded in the report's manifest and identical across runs.
    paths_a = _paths(first.manifest.sources)
    paths_b = _paths(second.manifest.sources)
    assert paths_a == paths_b == sorted(str(p) for p in Path(GOLDEN / "extxyz").glob("*/*.extxyz"))
    # Report order = manifest order = the deterministic (sorted) resolution.
    assert [e.source for e in first.entries] == paths_a
    assert [e.source for e in second.entries] == paths_a
    assert len(paths_a) == 3  # co-in-cell, mlip-labeled-2frame, stress6-voigt


def test_manifest_order_is_processing_and_report_order() -> None:
    sources: list[SourceEntry | str] = [str(MLIP), str(WATER), str(CO_IN_CELL)]
    report = run_batch(BatchManifest(sources=sources, target="extxyz"), _registry())
    assert [e.source for e in report.entries] == sources
    assert _paths(report.manifest.sources) == sources


# --- fail_fast (done-means 4) -----------------------------------------------------------------


def test_fail_fast_stops_at_first_non_success_default_completes() -> None:
    sources: list[SourceEntry | str] = [str(WATER), str(MLIP)]
    reg = _registry()
    # Default: partial completion with per-file honesty — the batch always completes.
    full = run_batch(BatchManifest(sources=sources, target="extxyz"), reg)
    assert len(full.entries) == 2
    # fail_fast: stops at the first non-converted entry, report still complete and honest.
    fast = run_batch(BatchManifest(sources=sources, target="extxyz"), reg, fail_fast=True)
    assert [e.source for e in fast.entries] == [str(WATER), str(MLIP)]
    assert [e.status for e in fast.entries] == ["converted", "refused"]


# --- presets + per-file overrides (the shared-settings surface) -------------------------------


def test_manifest_recovery_presets_resolve_an_otherwise_refused_conversion() -> None:
    report = run_batch(
        BatchManifest(
            sources=[str(WATER)],
            target="poscar",
            recovery_choices=[
                "frame_selection=last",
                "missing_lattice=bounding_box,padding_ang=5.0",
            ],
        ),
        _registry(),
    )
    (entry,) = report.entries
    assert entry.status == "converted"
    assert entry.conversion is not None
    assert {a.scenario for a in entry.conversion.assumptions} == {
        "frame_selection",
        "missing_lattice",
    }


def test_per_file_override_replaces_shared_settings() -> None:
    # strict mode refuses the co-in-cell → poscar loss unless acknowledged; the override
    # acknowledges for exactly that file while the shared setting stays strict.
    refused = run_batch(
        BatchManifest(sources=[str(CO_IN_CELL)], target="poscar", mode="strict"),
        _registry(),
    )
    (refused_entry,) = refused.entries
    assert refused_entry.status == "refused"
    assert refused_entry.conversion is not None
    assert refused_entry.conversion.refusal is not None
    assert refused_entry.conversion.refusal["code"] == "UNACKNOWLEDGED_LOSS"

    acknowledged = run_batch(
        BatchManifest(
            sources=[
                SourceEntry(
                    path=str(CO_IN_CELL),
                    override=SourceOverride(acknowledge_loss=True),
                )
            ],
            target="poscar",
            mode="strict",
        ),
        _registry(),
    )
    (ok_entry,) = acknowledged.entries
    assert ok_entry.status == "converted"


def test_one_file_manifest_behaves_like_an_ordinary_conversion(tmp_path: Path) -> None:
    out = tmp_path / "out"
    report = run_batch(
        BatchManifest(sources=[str(WATER)], target="extxyz"),
        _registry(),
        output=out,
    )
    assert report.tallies.total == 1 and report.tallies.converted == 1
    assert (out / "water_traj.extxyz").is_file()


# --- per-file output naming + collisions ------------------------------------------------------


def test_per_file_outputs_written_with_target_suffix(tmp_path: Path) -> None:
    out = tmp_path / "converted"
    report = run_batch(
        BatchManifest(sources=[str(WATER), str(CO_IN_CELL)], target="extxyz"),
        _registry(),
        output=out,
    )
    assert report.tallies.converted == 2
    assert (out / "water_traj.extxyz").read_bytes()
    assert (out / "sample.extxyz").read_bytes()
    # POSCAR/CONTCAR take no extension (the single-file CLI convention).
    poscar_out = tmp_path / "poscar"
    run_batch(
        BatchManifest(
            sources=[str(WATER)],
            target="poscar",
            recovery_choices=[
                "frame_selection=last",
                "missing_lattice=bounding_box,padding_ang=5.0",
            ],
        ),
        _registry(),
        output=poscar_out,
    )
    assert (poscar_out / "water_traj").is_file()


def test_output_name_collision_is_a_manifest_error(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "same.xyz").write_text("1\nx\nH 0 0 0\n")
    (b / "same.xyz").write_text("1\nx\nH 0 0 0\n")
    with pytest.raises(BatchManifestError, match="collide"):
        run_batch(
            BatchManifest(sources=[str(a / "same.xyz"), str(b / "same.xyz")], target="extxyz"),
            _registry(),
            output=tmp_path / "out",
        )


# --- caller mistakes are clean errors, never partial runs --------------------------------------


def test_empty_sources_is_a_manifest_error() -> None:
    with pytest.raises(BatchManifestError, match="no files"):
        run_batch(BatchManifest(sources=[], target="extxyz"), _registry())


def test_glob_matching_nothing_is_a_manifest_error() -> None:
    with pytest.raises(BatchManifestError, match="matched no files"):
        run_batch(
            BatchManifest(sources=["tests/golden/nonexistent-*.xyz"], target="extxyz"),
            _registry(),
        )


def test_missing_literal_source_is_a_manifest_error() -> None:
    with pytest.raises(BatchManifestError, match="does not exist"):
        run_batch(
            BatchManifest(sources=["tests/golden/no-such-file.xyz"], target="extxyz"),
            _registry(),
        )


def test_unknown_target_is_a_manifest_error() -> None:
    with pytest.raises(BatchManifestError, match="unknown target format"):
        run_batch(BatchManifest(sources=[str(WATER)], target="not-a-format"), _registry())


def test_malformed_recovery_preset_is_a_manifest_error() -> None:
    with pytest.raises(RecoveryPresetError, match="SCENARIO=CHOICE"):
        run_batch(
            BatchManifest(
                sources=[str(WATER)],
                target="extxyz",
                recovery_choices=["frame_selection"],
            ),
            _registry(),
        )


# --- the scope boundary is enforced by construction -------------------------------------------


def test_selection_split_dedup_keys_are_rejected(tmp_path: Path) -> None:
    # Selection and curation are scientific judgments about data, not translations of it
    # (roadmap §11): the manifest has *no fields* for them, and a manifest carrying one is
    # rejected — the absence is enforced, not merely omitted.
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(f"sources:\n  - {WATER}\ntarget: extxyz\nsplit:\n  train: 0.8\n")
    with pytest.raises(BatchManifestError, match="split"):
        load_manifest(manifest)


def test_malformed_yaml_is_a_manifest_error(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("sources: [\n  - unclosed\n")
    with pytest.raises(BatchManifestError, match="malformed manifest"):
        load_manifest(manifest)


# --- assemble mode (M54-S2): N sources → one artifact + per-contribution validation -----------


def _other_triatomic(tmp_path: Path) -> Path:
    other = tmp_path / "other.xyz"
    other.write_text("3\nother\nH 0 0 0\nH 0 0 1\nO 0 1 0\n")
    return other


def _frames_of(reg: Registry, path: Path) -> list[tuple[list[str], list[list[float]]]]:
    """(species, positions) per frame, for frame-order assertions against the assembled file."""
    from xtalate.sdk.plugins import ParserPlugin  # noqa: F401  (typing only)

    parser = reg.get_parser("extxyz")
    canonical = parser.parse(io.BytesIO(path.read_bytes()), filename=path.name).canonical
    return [(list(f.atoms.symbols), [list(p) for p in f.atoms.positions]) for f in canonical.frames]


def test_assemble_same_composition_produces_one_validated_artifact(tmp_path: Path) -> None:
    # N sources of one composition → one extXYZ whose per-contribution validations are all green
    # and which *does* re-parse as one object, in manifest order.
    other = _other_triatomic(tmp_path)
    reg = _registry()
    artifact = tmp_path / "train.extxyz"
    report = run_batch(
        BatchManifest(sources=[str(WATER), str(other)], target="extxyz", output_mode="assemble"),
        reg,
        output=artifact,
    )
    assert report.tallies.converted == 2
    assert [e.status for e in report.entries] == ["converted", "converted"]
    assert all(e.validation is not None and e.validation.status == "passed" for e in report.entries)
    assert report.note is None  # constant-N across sources: no variable-N statement
    assert artifact.is_file()

    # The one artifact re-parses as one object with frames in manifest order: water's two frames
    # (3 atoms each) then the other source's one frame (3 atoms) — constant-N throughout.
    assembled = _frames_of(reg, artifact)
    assert len(assembled) == 3
    assert assembled == _frames_of(reg, WATER) + _frames_of(reg, other)


def test_assemble_mixed_composition_records_dataset_level_variable_n_note(tmp_path: Path) -> None:
    # water (3 atoms) + co-in-cell (2 atoms): the assembled file has variable N across frames.
    # Per-contribution validations stay green; the single-object re-parse refuses the *existing*
    # EXTXYZ_VARIABLE_ATOM_COUNT, stated as a dataset-level note — never a per-file loss.
    reg = _registry()
    artifact = tmp_path / "mixed.extxyz"
    report = run_batch(
        BatchManifest(
            sources=[str(WATER), str(CO_IN_CELL)],
            target="extxyz",
            output_mode="assemble",
        ),
        reg,
        output=artifact,
    )
    assert [e.status for e in report.entries] == ["converted", "converted"]
    assert all(e.validation is not None and e.validation.status == "passed" for e in report.entries)
    assert report.note is not None
    assert "EXTXYZ_VARIABLE_ATOM_COUNT" in report.note
    assert f"{WATER}: 3" in report.note and f"{CO_IN_CELL}: 2" in report.note

    # The whole-file re-parse refuses exactly as the note says (the existing parser behaviour).
    parser = reg.get_parser("extxyz")
    from xtalate.sdk import ParseError

    with pytest.raises(ParseError) as excinfo:
        parser.parse(io.BytesIO(artifact.read_bytes()), filename="mixed.extxyz")
    assert excinfo.value.issues[0].code == "EXTXYZ_VARIABLE_ATOM_COUNT"


def test_assemble_non_append_capable_target_refuses_clearly() -> None:
    # A single-structure target (declared max_frames=1) and a multi-frame target outside the
    # append-capable set both refuse — never a silent fallback to per-file.
    with pytest.raises(BatchManifestError, match="max_frames=1"):
        run_batch(
            BatchManifest(sources=[str(WATER)], target="poscar", output_mode="assemble"),
            _registry(),
        )
    with pytest.raises(BatchManifestError, match="append-capable"):
        run_batch(
            BatchManifest(sources=[str(WATER)], target="xdatcar", output_mode="assemble"),
            _registry(),
        )


def test_assemble_keeps_refused_and_failed_segments_out(tmp_path: Path) -> None:
    # A refusal (stress carry without a preset) never enters the assembled artifact; its entry is
    # still recorded, and the artifact holds only the converted sources' frames.
    reg = _registry()
    artifact = tmp_path / "partial.extxyz"
    report = run_batch(
        BatchManifest(sources=[str(WATER), str(MLIP)], target="extxyz", output_mode="assemble"),
        reg,
        output=artifact,
    )
    assert [e.status for e in report.entries] == ["converted", "refused"]
    assert report.tallies.refused == 1
    # Only water's 2 frames are in the artifact; constant-N, so no variable-N note.
    assert len(_frames_of(reg, artifact)) == 2
    assert report.note is None
