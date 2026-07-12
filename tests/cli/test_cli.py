"""CLI tests (M6, MASTER_SPEC Appendix A).

Drives the ``main(argv)`` entry point end to end and pins the exit-code contract (§A.2) that makes
the CLI CI-native — the load-bearing promise for the pipeline persona — plus the report renderings
and the two ``validate`` modes. The CLI is a thin presenter, so these assert *behavior and exit
codes*, not exact wording.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xtalate.cli.main import (
    EXIT_OK,
    EXIT_PARSE_ERROR,
    EXIT_REFUSED,
    EXIT_USAGE,
    EXIT_VALIDATION_FAILED,
    main,
)

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = str(GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
CO_IN_CELL = str(GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")

_RECOVER = [
    "--recover",
    "frame_selection=last",
    "--recover",
    "missing_lattice=bounding_box,padding_ang=5.0",
]


# --- inspect -------------------------------------------------------------------------------------


def test_inspect_renders_inventory(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inspect", WATER]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Plain XYZ [xyz]" in out
    assert "✓ atoms.positions" in out
    assert "✗ cell.lattice_vectors" in out
    assert "xyz:comment" in out  # the carried-through extra is shown.


def test_inspect_json_is_valid_discovery_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inspect", WATER, "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"]["format_id"] == "xyz"
    assert len(payload["fields"]) == 16  # complete over the canonical leaf paths.


def test_inspect_writes_report_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "discovery.json"
    assert main(["inspect", WATER, "--report", str(report)]) == EXIT_OK
    assert json.loads(report.read_text())["structure"]["frame_count"] == 2


def test_inspect_unknown_format_exits_parse_error(tmp_path: Path) -> None:
    junk = tmp_path / "x.bin"
    junk.write_text("this is not a chemistry file at all\n")
    assert main(["inspect", str(junk)]) == EXIT_PARSE_ERROR


# --- convert -------------------------------------------------------------------------------------


def test_convert_with_recovery_succeeds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "POSCAR"
    conv = tmp_path / "conv.json"
    val = tmp_path / "val.json"
    code = main(
        [
            "convert",
            WATER,
            "--to",
            "poscar",
            "-o",
            str(out),
            *_RECOVER,
            "--report",
            str(conv),
            "--validation-report",
            str(val),
        ]
    )
    assert code == EXIT_OK
    assert out.exists()
    assert json.loads(conv.read_text())["status"] == "completed"
    assert json.loads(val.read_text())["status"] == "passed"
    printed = capsys.readouterr().out
    assert "Conversion Report" in printed and "Validation Report" in printed


def test_convert_refused_without_presets(tmp_path: Path) -> None:
    out = tmp_path / "POSCAR"
    assert main(["convert", WATER, "--to", "poscar", "-o", str(out)]) == EXIT_REFUSED
    assert not out.exists()  # a refused conversion produces no output file.


def test_convert_json_emits_both_reports(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["convert", WATER, "--to", "poscar", *_RECOVER, "--json"])
    assert code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["conversion_report"]["status"] == "completed"
    assert payload["validation_report"]["status"] == "passed"


def test_convert_bad_recover_spec_is_usage_error() -> None:
    assert main(["convert", WATER, "--to", "poscar", "--recover", "frame_selection"]) == EXIT_USAGE


def test_convert_unknown_tolerance_profile_is_usage_error() -> None:
    code = main(["convert", CO_IN_CELL, "--to", "poscar", "--tolerance-profile", "ultra"])
    assert code == EXIT_USAGE


# --- validate ------------------------------------------------------------------------------------


def test_validate_full_reparse_of_lossless_conversion(tmp_path: Path) -> None:
    out = tmp_path / "POSCAR"
    conv = tmp_path / "conv.json"
    assert (
        main(["convert", CO_IN_CELL, "--to", "poscar", "-o", str(out), "--report", str(conv)])
        == EXIT_OK
    )
    code = main(
        ["validate", "--output", str(out), "--source", CO_IN_CELL, "--conversion-report", str(conv)]
    )
    assert code == EXIT_OK


def test_validate_offline_refuses_when_conversion_had_supplied_fields(tmp_path: Path) -> None:
    out = tmp_path / "POSCAR"
    conv = tmp_path / "conv.json"
    main(["convert", WATER, "--to", "poscar", "-o", str(out), *_RECOVER, "--report", str(conv)])
    # The fabricated lattice cannot be reconstructed offline -> honest usage error, not a bad pass.
    code = main(
        ["validate", "--output", str(out), "--source", WATER, "--conversion-report", str(conv)]
    )
    assert code == EXIT_USAGE


def test_validate_rethreshold_reads_stored_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    val = tmp_path / "val.json"
    main(
        [
            "convert",
            WATER,
            "--to",
            "poscar",
            *_RECOVER,
            "--validation-report",
            str(val),
            "-o",
            str(tmp_path / "P"),
        ]
    )
    code = main(["validate", "--validation-report", str(val), "--tolerance-profile", "strict"])
    assert code == EXIT_OK
    assert "tolerance profile: strict" in capsys.readouterr().out


# --- capabilities ------------------------------------------------------------------------------


def test_capabilities_all_formats(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["capabilities"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "[poscar]" in out and "[xyz]" in out


def test_capabilities_one_format_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["capabilities", "poscar", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["poscar"]["write"]["required_fields"] == [
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
    ]


def test_capabilities_unknown_format_is_usage_error() -> None:
    assert main(["capabilities", "nosuchformat"]) == EXIT_USAGE


# --- top level -----------------------------------------------------------------------------------


def test_no_command_prints_help_and_exits_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_USAGE


def test_strict_mode_unacknowledged_loss_refuses(tmp_path: Path) -> None:
    # strict mode refuses reductive loss unless acknowledged (Part 4 §4) — a refusal, exit 2.
    code = main(
        ["convert", CO_IN_CELL, "--to", "poscar", "-o", str(tmp_path / "P"), "--mode", "strict"]
    )
    assert code == EXIT_REFUSED
    # …and proceeds once acknowledged.
    code = main(
        [
            "convert",
            CO_IN_CELL,
            "--to",
            "poscar",
            "-o",
            str(tmp_path / "P2"),
            "--mode",
            "strict",
            "--acknowledge-loss",
        ]
    )
    assert code in (EXIT_OK, EXIT_VALIDATION_FAILED)
