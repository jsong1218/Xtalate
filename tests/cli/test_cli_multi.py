"""Multi-input, glob/directory fan-out, and stdin/stdout for `xtalate convert` (QoL Q3)."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_PARSE_ERROR, EXIT_REFUSED, EXIT_USAGE, main

GOLDEN = Path(__file__).parent.parent / "golden"
CO = GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz"  # converts to poscar cleanly
WATER = GOLDEN / "xyz" / "water-traj" / "water_traj.xyz"  # needs recovery for poscar (refused)


def _stage(tmp_path: Path, names: dict[str, Path]) -> Path:
    src = tmp_path / "in"
    src.mkdir()
    for name, original in names.items():
        shutil.copy(original, src / name)
    return src


def test_two_inputs_need_an_output_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    rc = main(["convert", str(src / "a.extxyz"), str(src / "b.extxyz"), "--to", "poscar"])
    assert rc == EXIT_USAGE
    assert "-o DIR" in capsys.readouterr().err


def test_fan_out_requires_an_explicit_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    rc = main(["convert", str(src / "a.extxyz"), str(src / "b.extxyz"), "-o", str(tmp_path / "o")])
    assert rc == EXIT_USAGE
    assert "--to" in capsys.readouterr().err


def test_fan_out_writes_one_output_per_input_and_one_summary_line_each(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    out = tmp_path / "out"
    rc = main(
        ["convert", str(src / "a.extxyz"), str(src / "b.extxyz"), "--to", "poscar", "-o", str(out)]
    )
    text = capsys.readouterr().out
    assert rc == EXIT_OK
    assert sorted(p.name for p in out.iterdir()) == ["a.poscar", "b.poscar"]
    summary = [ln for ln in text.splitlines() if "->" in ln]
    assert len(summary) == 2 and "a.extxyz" in summary[0] and "completed" in summary[0]


def test_fan_out_uses_the_targets_declared_extension(tmp_path: Path) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    out = tmp_path / "out"
    rc = main(
        ["convert", str(src / "a.extxyz"), str(src / "b.extxyz"), "--to", "cif", "-o", str(out)]
    )
    assert rc == EXIT_OK
    assert sorted(p.name for p in out.iterdir()) == ["a.cif", "b.cif"]


def test_glob_pattern_unexpanded_by_shell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO, "c.txt": CO})
    out = tmp_path / "out"
    rc = main(["convert", str(src / "*.extxyz"), "--to", "poscar", "-o", str(out)])
    assert rc == EXIT_OK, capsys.readouterr().err
    assert sorted(p.name for p in out.iterdir()) == ["a.poscar", "b.poscar"]


def test_glob_with_no_match_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["convert", str(tmp_path / "*.nothing"), "--to", "poscar", "-o", str(tmp_path / "o")])
    assert rc == EXIT_USAGE
    assert "matched no files" in capsys.readouterr().err


def test_directory_input_fans_out_and_exit_code_is_most_severe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"co.extxyz": CO, "water.xyz": WATER})
    out = tmp_path / "out"
    rc = main(["convert", str(src), "--to", "poscar", "-o", str(out)])
    text = capsys.readouterr().out
    assert rc == EXIT_REFUSED
    assert (out / "co.poscar").exists()
    assert not (out / "water.poscar").exists()
    assert "water.xyz" in text and "refused" in text.lower()


def test_unknown_format_in_directory_is_reported_not_dropped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"co.extxyz": CO})
    (src / "notes.bin").write_bytes(b"\x00\x01not a structure")
    rc = main(["convert", str(src), "--to", "poscar", "-o", str(tmp_path / "out")])
    text = capsys.readouterr()
    assert rc == EXIT_PARSE_ERROR
    assert "notes.bin" in text.out and "UNKNOWN_FORMAT" in text.out
    assert (tmp_path / "out" / "co.poscar").exists()  # the good file still converted


def test_empty_directory_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = main(["convert", str(empty), "--to", "poscar", "-o", str(tmp_path / "o")])
    assert rc == EXIT_USAGE
    assert "no files to convert" in capsys.readouterr().err


def test_colliding_output_names_are_refused_before_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "a.xyz": WATER})
    out = tmp_path / "out"
    rc = main(
        ["convert", str(src / "a.extxyz"), str(src / "a.xyz"), "--to", "extxyz", "-o", str(out)]
    )
    assert rc == EXIT_USAGE
    assert "same output name" in capsys.readouterr().err
    assert not out.exists() or not any(out.iterdir())


def test_fan_out_json_is_an_array_of_per_file_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    out = tmp_path / "out"
    rc = main(
        [
            "convert",
            str(src / "a.extxyz"),
            str(src / "b.extxyz"),
            "--to",
            "poscar",
            "-o",
            str(out),
            "--json",
        ]
    )
    payload: Any = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK
    assert isinstance(payload, list) and len(payload) == 2
    assert payload[0]["input"].endswith("a.extxyz") and payload[0]["exit_code"] == EXIT_OK
    assert payload[0]["conversion_report"]["status"] == "completed"


def test_fan_out_rejects_a_single_report_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    rc = main(
        [
            "convert",
            str(src / "a.extxyz"),
            str(src / "b.extxyz"),
            "--to",
            "poscar",
            "-o",
            str(tmp_path / "o"),
            "--report",
            str(tmp_path / "r.json"),
        ]
    )
    assert rc == EXIT_USAGE
    assert "--report" in capsys.readouterr().err


def test_single_file_behaviour_unchanged(tmp_path: Path) -> None:
    out = tmp_path / "one.poscar"
    assert main(["convert", str(CO), "--to", "poscar", "-o", str(out)]) == EXIT_OK
    assert out.is_file()


# --- stdin / stdout ---------------------------------------------------------------------------


class _FakeStdin:
    """Just enough of ``sys.stdin`` for the CLI: a ``.buffer`` with the bytes."""

    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


def test_stdin_requires_a_format(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin(CO.read_bytes()))
    rc = main(["convert", "-", "--to", "poscar", "-o", "-"])
    assert rc == EXIT_USAGE
    assert "--from" in capsys.readouterr().err


def test_stdin_to_stdout_round_trip(
    monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin(CO.read_bytes()))
    rc = main(["convert", "-", "--from", "extxyz", "--to", "poscar", "-o", "-"])
    captured = capsysbinary.readouterr()
    assert rc == EXIT_OK
    assert b"Cartesian" in captured.out or b"Direct" in captured.out  # the POSCAR body
    assert b"Conversion Report" not in captured.out
    assert b"Conversion Report" in captured.err  # the human summary moved to stderr
    assert b"<stdin>" not in captured.out


def test_stdin_to_a_file_records_the_stdin_source_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin(CO.read_bytes()))
    out = tmp_path / "o.poscar"
    rc = main(["convert", "-", "--from", "extxyz", "--to", "poscar", "-o", str(out), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == EXIT_OK and out.is_file()
    assert payload["conversion_report"]["source"]["filename"] == "<stdin>"


def test_stdin_cannot_be_combined_with_other_inputs(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["convert", "-", str(CO), "--from", "extxyz", "--to", "poscar", "-o", "x"])
    assert rc == EXIT_USAGE
    assert "stdin" in capsys.readouterr().err


def test_json_with_stdout_output_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["convert", str(CO), "--to", "poscar", "-o", "-", "--json"])
    assert rc == EXIT_USAGE
    assert "--json" in capsys.readouterr().err


def test_stdout_output_with_multiple_inputs_is_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["convert", str(CO), str(CO), "--to", "poscar", "-o", "-"]) == EXIT_USAGE


def test_stdout_output_cannot_hold_a_directory_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["convert", str(CO), "--to", "deepmd_npy", "-o", "-"])
    assert rc == EXIT_USAGE
    assert "multi-file output" in capsys.readouterr().err


def test_stdout_status_goes_to_stderr_not_stdout(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    rc = main(["convert", str(CO), "--to", "poscar", "-o", "-"])
    captured = capsysbinary.readouterr()
    assert rc == EXIT_OK
    assert b"Conversion Report" not in captured.out
    assert b"Conversion Report" in captured.err


def test_refused_stdout_conversion_writes_nothing_to_stdout(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    rc = main(["convert", str(WATER), "--to", "poscar", "-o", "-"])
    captured = capsysbinary.readouterr()
    assert rc == EXIT_REFUSED
    assert captured.out == b""


def test_batch_conflicts_with_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["convert", "--batch", "m.json", "-o", "-"]) == EXIT_USAGE


# --- Fan-out dry-run wording and input protection (M1, I3; D303) ------------------------------

SLAB_EXTXYZ = (
    b'2\nLattice="5 0 0 0 5 0 0 0 5" Properties=species:S:1:pos:R:3 pbc="T T F"\nO 0 0 0\nH 0 0 1\n'
)


def test_fan_out_dry_run_says_would_refuse_for_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"co.extxyz": CO})
    (src / "slab.extxyz").write_bytes(SLAB_EXTXYZ)
    rc = main(["convert", str(src), "--to", "deepmd_npy", "-o", str(tmp_path / "o"), "--dry-run"])
    lines = {ln.split()[0]: ln for ln in capsys.readouterr().out.splitlines() if "->" in ln}
    assert rc == EXIT_REFUSED
    assert lines["co.extxyz"].endswith("would complete")
    assert lines["slab.extxyz"].endswith("would refuse")
    assert not (tmp_path / "o").exists()


def test_fan_out_dry_run_keeps_needs_recovery_for_a_pause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"co.extxyz": CO, "water.xyz": WATER})
    rc = main(["convert", str(src), "--to", "poscar", "-o", str(tmp_path / "o"), "--dry-run"])
    lines = {ln.split()[0]: ln for ln in capsys.readouterr().out.splitlines() if "->" in ln}
    assert rc == EXIT_REFUSED
    assert lines["co.extxyz"].endswith("would complete")
    assert lines["water.xyz"].endswith("needs recovery")


def test_fan_out_refuses_to_overwrite_one_of_its_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `convert in/ -o in --to extxyz` would write in/foo.extxyz over the input in/foo.extxyz.
    src = _stage(tmp_path, {"foo.extxyz": CO, "bar.xyz": WATER})
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    rc = main(["convert", str(src), "-o", str(src), "--to", "extxyz"])
    err = capsys.readouterr().err
    assert rc == EXIT_USAGE
    assert "foo.extxyz" in err and "input" in err
    # Nothing was written: not even the non-colliding bar.extxyz.
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before


def test_fan_out_input_protection_sees_through_a_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = _stage(tmp_path, {"foo.extxyz": CO, "bar.extxyz": CO})
    monkeypatch.chdir(src)
    rc = main(
        ["convert", "foo.extxyz", "bar.extxyz", "-o", str(src / ".." / "in"), "--to", "extxyz"]
    )
    assert rc == EXIT_USAGE
    assert "input" in capsys.readouterr().err


def test_fan_out_still_overwrites_an_existing_non_input_file(tmp_path: Path) -> None:
    # Documented behaviour (docs/cli.md): only the inputs are protected; an existing file in -o DIR
    # that is not an input is replaced, as a single-file -o PATH is.
    src = _stage(tmp_path, {"a.extxyz": CO, "b.extxyz": CO})
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.poscar").write_text("stale\n")
    rc = main(["convert", str(src), "--to", "poscar", "-o", str(out)])
    assert rc == EXIT_OK
    assert (out / "a.poscar").read_text() != "stale\n"
