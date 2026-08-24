"""CLI ``convert --batch`` tests (v1.5 M54-S3, MASTER_SPEC Appendix A).

The CLI form is a thin transport over the proven ``run_batch``: a malformed manifest is a usage
error (exit 1), ``--json`` prints the ``BatchReport`` **verbatim** (the model round-trips under
``extra=\"forbid\"`` — nothing invented, nothing dropped), the human rendering is a view that
references each file, and the exit code is the **worst per-file outcome** under the existing 0–5
vocabulary. The non-features (selection/split/dedup) are refused **by construction** — no flag
exists and a manifest carrying such a key is rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ase import Atoms
from ase.db import connect

from xtalate.cli.main import (
    EXIT_OK,
    EXIT_PARSE_ERROR,
    EXIT_REFUSED,
    EXIT_USAGE,
    main,
)
from xtalate.conversion import BatchReport

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = GOLDEN / "xyz" / "water-traj" / "water_traj.xyz"
CO_IN_CELL = GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz"
MLIP = GOLDEN / "extxyz" / "mlip-labeled-2frame" / "mlip_labeled.extxyz"


def _manifest(tmp_path: Path, *, body: str, name: str = "manifest.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


# --- exit codes: the worst per-file outcome (0–5) ---------------------------------------------


def test_batch_all_clean_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: extxyz\n",
    )
    out = tmp_path / "out"
    assert main(["convert", "--batch", str(manifest), "-o", str(out)]) == EXIT_OK
    # The human rendering is a view that references each file and the tallies.
    human = capsys.readouterr().out
    assert "Batch Report" in human
    assert str(WATER) in human
    assert "converted [passed]" in human
    assert (out / "water_traj.extxyz").is_file()


def test_batch_one_refusal_exits_refused(tmp_path: Path) -> None:
    # water → poscar without recovery presets refuses (RECOVERY_REQUIRED): exit 2.
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: poscar\n",
    )
    out = tmp_path / "out"
    assert main(["convert", "--batch", str(manifest), "-o", str(out)]) == EXIT_REFUSED


def test_batch_one_parse_error_exits_parse_error(tmp_path: Path) -> None:
    junk = tmp_path / "junk.bin"
    junk.write_text("this is not a chemistry file at all\n")
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {junk}\ntarget: extxyz\n",
    )
    out = tmp_path / "out"
    assert main(["convert", "--batch", str(manifest), "-o", str(out)]) == EXIT_PARSE_ERROR


def test_batch_fail_fast_stops_and_exits_on_first_non_success(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\n  - {MLIP}\ntarget: extxyz\n",
    )
    out = tmp_path / "out"
    code = main(["convert", "--batch", str(manifest), "-o", str(out), "--fail-fast"])
    assert code == EXIT_REFUSED
    # Only water's output exists — the batch stopped at the refusal.
    assert (out / "water_traj.extxyz").is_file()


def test_batch_fail_fast_on_a_non_final_source_still_exits_cleanly(tmp_path: Path) -> None:
    # The non-success is the *first* source, so resolved sources remain unprocessed after the
    # fail-fast break: entries is a short prefix of manifest.sources. The worst-per-file fold
    # must pair by position and exit cleanly, never raise on the short read (regression: a strict
    # zip in _batch_exit_code crashed this path with a traceback).
    junk = tmp_path / "junk.bin"
    junk.write_text("this is not a chemistry file at all\n")
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {junk}\n  - {WATER}\ntarget: extxyz\n",
    )
    out = tmp_path / "out"
    code = main(["convert", "--batch", str(manifest), "-o", str(out), "--fail-fast"])
    assert code == EXIT_PARSE_ERROR
    # The batch stopped at the first source; water was never processed.
    assert not (out / "water_traj.extxyz").exists()


# --- --json prints the BatchReport verbatim ---------------------------------------------------


def test_batch_json_is_the_report_verbatim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\n  - {CO_IN_CELL}\ntarget: extxyz\n",
    )
    out = tmp_path / "out"
    assert main(["convert", "--batch", str(manifest), "-o", str(out), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    # extra="forbid" means a payload with invented fields fails validation — verbatim by proof.
    report = BatchReport.model_validate(payload)
    assert report.tallies.total == 2
    assert report.tallies.converted == 2
    assert [e.source for e in report.entries] == [str(WATER), str(CO_IN_CELL)]
    assert report.manifest.target == "extxyz"
    # The per-file reports are embedded, not summarized: the entry *is* a ConversionReport.
    assert report.entries[0].conversion is not None
    assert report.entries[0].conversion.status == "completed"


def test_batch_json_honors_stdout_purity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Status lines go to stderr so --json stdout stays pure JSON (the single-file convention).
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: extxyz\n",
    )
    out = tmp_path / "out"
    assert main(["convert", "--batch", str(manifest), "-o", str(out), "--json"]) == EXIT_OK
    captured = capsys.readouterr()
    json.loads(captured.out)  # pure JSON
    assert "Wrote" in captured.err


# --- assemble mode through the CLI -------------------------------------------------------------


def test_batch_assemble_writes_one_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest(
        tmp_path,
        body=(f"sources:\n  - {WATER}\n  - {CO_IN_CELL}\ntarget: extxyz\noutput_mode: assemble\n"),
    )
    artifact = tmp_path / "train.extxyz"
    assert main(["convert", "--batch", str(manifest), "-o", str(artifact)]) == EXIT_OK
    human = capsys.readouterr().out
    assert "converted [passed]" in human
    assert artifact.is_file() and artifact.read_bytes()
    # The mixed-composition dataset-level note is part of the human view (never a per-file loss).
    assert "EXTXYZ_VARIABLE_ATOM_COUNT" in human


# --- multi-structure container fan-out through the CLI (M55-S3) --------------------------------


def _multi_row_db(tmp_path: Path, *structures: Atoms, name: str = "dataset.db") -> Path:
    path = tmp_path / name
    db = connect(str(path), use_lock_file=False)
    for atoms in structures:
        db.write(atoms)
    return path


def test_batch_multi_row_db_fans_out_and_assembles_a_training_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The milestone's user-facing journey: `xtalate convert --batch <manifest with a multi-row .db>
    # --to extxyz` assembles the rows into one training set. --json shows the per-row entries
    # (row-qualified sources, verbatim reports); the exit code is the worst per-file outcome (0).
    db = _multi_row_db(
        tmp_path,
        Atoms("CO", positions=[[0.0, 0.0, 0.0], [1.13, 0.0, 0.0]]),
        Atoms("CO", positions=[[0.0, 0.0, 0.0], [1.15, 0.0, 0.0]]),
    )
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {db}\ntarget: extxyz\noutput_mode: assemble\n",
    )
    artifact = tmp_path / "train.extxyz"
    assert main(["convert", "--batch", str(manifest), "-o", str(artifact), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    report = BatchReport.model_validate(payload)
    assert [e.source for e in report.entries] == [f"{db}::row=0", f"{db}::row=1"]
    assert all(e.status == "converted" for e in report.entries)
    assert report.note is not None and "per-row conversions" in report.note
    assert artifact.is_file() and artifact.read_bytes()


# --- caller mistakes are usage errors (exit 1) -------------------------------------------------


def test_batch_malformed_manifest_exits_usage(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, body="sources: [\n  - unclosed\n")
    assert main(["convert", "--batch", str(manifest), "-o", str(tmp_path / "out")]) == EXIT_USAGE


def test_batch_selection_split_dedup_key_rejected(tmp_path: Path) -> None:
    # The scope refusal, enforced not merely omitted: no manifest field / flag exists for
    # selection, splitting, or deduplication — a manifest carrying one is rejected (exit 1).
    manifest = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: extxyz\nselect:\n  species: Fe\n",
    )
    assert main(["convert", "--batch", str(manifest), "-o", str(tmp_path / "out")]) == EXIT_USAGE
    split = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: extxyz\nsplit:\n  train: 0.8\n",
        name="split.yaml",
    )
    assert main(["convert", "--batch", str(split), "-o", str(tmp_path / "out")]) == EXIT_USAGE


def test_batch_conflicting_per_file_flags_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, body=f"sources:\n  - {WATER}\ntarget: extxyz\n")
    # The manifest carries the shared settings; a conflicting CLI flag is a caller mistake.
    assert (
        main(
            [
                "convert",
                "--batch",
                str(manifest),
                "-o",
                str(tmp_path / "out"),
                "--recover",
                "frame_selection=last",
            ]
        )
        == EXIT_USAGE
    )
    assert (
        main(
            [
                "convert",
                "--batch",
                str(manifest),
                "-o",
                str(tmp_path / "out"),
                "--mode",
                "strict",
            ]
        )
        == EXIT_USAGE
    )


def test_batch_requires_output(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, body=f"sources:\n  - {WATER}\ntarget: extxyz\n")
    assert main(["convert", "--batch", str(manifest)]) == EXIT_USAGE


def test_batch_and_file_are_mutually_exclusive(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, body=f"sources:\n  - {WATER}\ntarget: extxyz\n")
    assert (
        main(["convert", str(WATER), "--batch", str(manifest), "-o", str(tmp_path / "out")])
        == EXIT_USAGE
    )


def test_batch_manifest_errors_exit_usage(tmp_path: Path) -> None:
    # An unknown target and a non-append-capable assemble are manifest errors: exit 1, clean.
    bad_target = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: not-a-format\n",
    )
    assert main(["convert", "--batch", str(bad_target), "-o", str(tmp_path / "out")]) == EXIT_USAGE
    assemble_poscar = _manifest(
        tmp_path,
        body=f"sources:\n  - {WATER}\ntarget: poscar\noutput_mode: assemble\n",
    )
    assert (
        main(["convert", "--batch", str(assemble_poscar), "-o", str(tmp_path / "x")]) == EXIT_USAGE
    )
