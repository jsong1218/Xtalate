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


_MB_TRAJ = (
    b"2\nProperties=species:S:1:pos:R:3:masses:R:1\nC 0.0 0.0 0.0 12.011\nO 1.1 0.0 0.0 15.999\n"
    b"2\nProperties=species:S:1:pos:R:3:masses:R:1\nC 0.0 0.0 0.0 12.011\nO 1.25 0.0 0.0 15.999\n"
)


def test_convert_maxwell_boltzmann_chain_via_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A plain XYZ trajectory has no masses, so `maxwell_boltzmann` chains `missing_masses`; the CLI
    # must parse `temperature_K`/`seed` and thread both recoveries through to a completed convert.
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
            "--recover",
            "frame_selection=last",
            "--recover",
            "missing_lattice=bounding_box,padding_ang=5.0",
            "--recover",
            "missing_masses=standard_masses",
            "--recover",
            "missing_velocities=maxwell_boltzmann,temperature_K=300,seed=42",
            "--report",
            str(conv),
            "--validation-report",
            str(val),
        ]
    )
    assert code == EXIT_OK
    report = json.loads(conv.read_text())
    assert report["status"] == "completed"
    supplied = {e["path"] for e in report["supplied"]}
    assert {"dynamics.velocities", "atoms.masses"} <= supplied
    assert json.loads(val.read_text())["status"] in ("passed", "passed_with_warnings")


def test_convert_maxwell_boltzmann_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    args = [
        "convert",
        WATER,
        "--to",
        "poscar",
        "--recover",
        "frame_selection=last",
        "--recover",
        "missing_lattice=bounding_box,padding_ang=5.0",
        "--recover",
        "missing_masses=standard_masses",
        "--recover",
        "missing_velocities=maxwell_boltzmann,temperature_K=300,seed=42",
    ]
    first = tmp_path / "POSCAR1"
    second = tmp_path / "POSCAR2"
    assert main([*args, "-o", str(first)]) == EXIT_OK
    assert main([*args, "-o", str(second)]) == EXIT_OK
    assert first.read_bytes() == second.read_bytes()


def test_convert_done_criterion_masses_source(tmp_path: Path) -> None:
    # The literal done-criterion command: the source already carries masses, so only the three
    # documented `--recover` flags are needed (no explicit missing_masses).
    traj = tmp_path / "traj.extxyz"
    traj.write_bytes(_MB_TRAJ)
    out = tmp_path / "POSCAR"
    code = main(
        [
            "convert",
            str(traj),
            "--to",
            "poscar",
            "-o",
            str(out),
            "--recover",
            "missing_lattice=bounding_box,padding_ang=5.0",
            "--recover",
            "frame_selection=last",
            "--recover",
            "missing_velocities=maxwell_boltzmann,temperature_K=300,seed=42",
        ]
    )
    assert code == EXIT_OK
    assert out.exists()


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


def test_convert_json_with_output_still_writes_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --json and -o are independent outputs: the reports go to stdout as JSON, the artifact to the
    # file. --json previously suppressed the file write entirely (silent no-op, exit 0). stdout must
    # stay pure JSON (the "Wrote …" notice goes to stderr).
    out = tmp_path / "POSCAR"
    code = main(["convert", WATER, "--to", "poscar", *_RECOVER, "-o", str(out), "--json"])
    assert code == EXIT_OK
    assert out.exists() and out.read_bytes()
    captured = capsys.readouterr()
    json.loads(captured.out)  # stdout parses as JSON — no notice leaked in
    assert "Wrote" in captured.err


def test_convert_bad_recover_choice_is_clean_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # An unoffered recovery choice is a caller error → clean exit 1, no traceback.
    code = main(
        [
            "convert",
            WATER,
            "--to",
            "poscar",
            "--recover",
            "frame_selection=last",
            "--recover",
            "missing_lattice=bogus",
        ]
    )
    assert code == EXIT_USAGE
    assert "Traceback" not in capsys.readouterr().err


def test_convert_bad_recover_spec_is_usage_error() -> None:
    assert main(["convert", WATER, "--to", "poscar", "--recover", "frame_selection"]) == EXIT_USAGE


def test_convert_unknown_tolerance_profile_is_usage_error() -> None:
    code = main(["convert", CO_IN_CELL, "--to", "poscar", "--tolerance-profile", "ultra"])
    assert code == EXIT_USAGE


# --- custom tolerance-table files (M9, Part 5 §4.4) ----------------------------------------------

_CUSTOM_TABLE = "name: tight-forces\nquantities:\n  forces: {warn: 1.0e-8, fail: 1.0e-6}\n"


def test_convert_with_custom_tolerance_file(tmp_path: Path) -> None:
    table = tmp_path / "custom.yaml"
    table.write_text(_CUSTOM_TABLE)
    conv = tmp_path / "conv.json"
    val = tmp_path / "val.json"
    code = main(
        [
            "convert",
            CO_IN_CELL,
            "--to",
            "extxyz",
            "-o",
            str(tmp_path / "out.extxyz"),
            "--tolerance-profile",
            str(table),
            "--report",
            str(conv),
            "--validation-report",
            str(val),
        ]
    )
    assert code == EXIT_OK
    # The custom profile's name is embedded in the Validation Report, keeping it self-contained.
    assert json.loads(val.read_text())["tolerance_profile"]["name"] == "tight-forces"


def test_convert_with_custom_tolerance_json_file(tmp_path: Path) -> None:
    # M9 claims YAML *or* JSON tolerance tables (D48, one `yaml.safe_load` for both). The YAML half
    # is covered above; this pins the JSON half so the claim does not ride solely on YAML being a
    # JSON superset. A `.json` table with the same content must produce the same embedded profile.
    table = tmp_path / "custom.json"
    table.write_text(
        json.dumps({"name": "tight-forces", "quantities": {"forces": {"warn": 1e-8, "fail": 1e-6}}})
    )
    val = tmp_path / "val.json"
    code = main(
        [
            "convert",
            CO_IN_CELL,
            "--to",
            "extxyz",
            "-o",
            str(tmp_path / "out.extxyz"),
            "--tolerance-profile",
            str(table),
            "--validation-report",
            str(val),
        ]
    )
    assert code == EXIT_OK
    assert json.loads(val.read_text())["tolerance_profile"]["name"] == "tight-forces"


def test_validate_rethreshold_with_custom_tolerance_file(tmp_path: Path) -> None:
    # The M9 done-means: `--tolerance-profile ./custom.yaml` re-thresholds a stored report offline.
    val = tmp_path / "val.json"
    main(
        [
            "convert",
            CO_IN_CELL,
            "--to",
            "extxyz",
            "-o",
            str(tmp_path / "out.extxyz"),
            "--validation-report",
            str(val),
        ]
    )
    table = tmp_path / "custom.yaml"
    table.write_text(_CUSTOM_TABLE)
    code = main(["validate", "--validation-report", str(val), "--tolerance-profile", str(table)])
    assert code == EXIT_OK


def test_convert_malformed_tolerance_file_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    table = tmp_path / "bad.yaml"
    table.write_text("quantities:\n  bogus: {warn: 1.0e-6, fail: 1.0e-4}\n")
    code = main(["convert", CO_IN_CELL, "--to", "extxyz", "--tolerance-profile", str(table)])
    assert code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "unknown tolerance quantity" in err and "Traceback" not in err


# --- convert: Slice 2 recovery paths -------------------------------------------------------------

_VASP4_POSCAR = """vasp4
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
2 1
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
  0.25 0.25 0.25
"""


def test_convert_split_all_writes_one_file_per_frame(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outdir = tmp_path / "frames"
    code = main(
        [
            "convert",
            WATER,
            "--to",
            "poscar",
            "-o",
            str(outdir),
            "--recover",
            "frame_selection=split_all",
            "--recover",
            "missing_lattice=bounding_box,padding_ang=3.0",
        ]
    )
    assert code == EXIT_OK
    written = sorted(p.name for p in outdir.iterdir())
    assert written == ["POSCAR_0000", "POSCAR_0001"]  # water-traj has 2 frames
    assert "Wrote 2 poscar file(s)" in capsys.readouterr().err


def test_convert_missing_species_recoverable_error_without_preset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "POSCAR"
    src.write_text(_VASP4_POSCAR)
    code = main(["convert", str(src), "--to", "poscar", "-o", str(tmp_path / "out")])
    assert code == EXIT_PARSE_ERROR
    err = capsys.readouterr().err
    assert "supply_species" in err and "recoverable" in err  # actionable message


def test_convert_missing_species_species_map_succeeds(tmp_path: Path) -> None:
    src = tmp_path / "POSCAR"
    src.write_text(_VASP4_POSCAR)
    conv = tmp_path / "conv.json"
    code = main(
        [
            "convert",
            str(src),
            "--to",
            "extxyz",
            "-o",
            str(tmp_path / "out.extxyz"),
            "--recover",
            "missing_species=species_map,species=H:O",
            "--report",
            str(conv),
        ]
    )
    assert code == EXIT_OK
    report = json.loads(conv.read_text())
    assert any(a["scenario"] == "missing_species" for a in report["assumptions"])
    assert "atoms.symbols" in {s["path"] for s in report["supplied"]}


def test_convert_missing_lattice_upload_reference_via_file_param(tmp_path: Path) -> None:
    # A no-lattice XYZ borrows its lattice from a reference POSCAR named by file=PATH.
    src = tmp_path / "mol.xyz"
    src.write_text("2\nf\nH 0 0 0\nH 0 0 0.8\n")
    ref = tmp_path / "REF"
    ref.write_text("ref\n1.0\n 5 0 0\n 0 5 0\n 0 0 5\nH\n2\nDirect\n 0 0 0\n 0.1 0.1 0.1\n")
    conv = tmp_path / "conv.json"
    code = main(
        [
            "convert",
            str(src),
            "--to",
            "poscar",
            "-o",
            str(tmp_path / "OUT"),
            "--recover",
            f"missing_lattice=upload_reference,file={ref}",
            "--report",
            str(conv),
        ]
    )
    assert code == EXIT_OK
    report = json.loads(conv.read_text())
    assert "cell.lattice_vectors" in {s["path"] for s in report["supplied"]}


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
