"""--quiet / --verbose, TTY progress and optional completion (QoL Q3)."""

from __future__ import annotations

import importlib
import io
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_USAGE, _Progress, main

cli_main = importlib.import_module(
    "xtalate.cli.main"
)  # `xtalate.cli.main` the attr is the function

GOLDEN = Path(__file__).parent.parent / "golden"
CO = str(GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")


def test_quiet_suppresses_status_but_still_writes_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "o.poscar"
    assert main(["convert", CO, "--to", "poscar", "-o", str(out), "--quiet"]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "" and out.is_file()


def test_quiet_never_hides_errors_or_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["convert", str(tmp_path / "missing.xyz"), "--to", "poscar", "-q"])
    assert rc != EXIT_OK
    assert capsys.readouterr().err != ""


def test_quiet_keeps_the_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["convert", CO, "--to", "poscar", "--json", "-q"]) == EXIT_OK
    assert capsys.readouterr().out.lstrip().startswith("{")


def test_quiet_suppresses_the_fan_out_summary_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "in"
    src.mkdir()
    shutil.copy(CO, src / "a.extxyz")
    shutil.copy(CO, src / "b.extxyz")
    out = tmp_path / "out"
    rc = main(["convert", str(src), "--to", "poscar", "-o", str(out), "-q"])
    assert rc == EXIT_OK
    assert capsys.readouterr().out == ""
    assert sorted(p.name for p in out.iterdir()) == ["a.poscar", "b.poscar"]


def test_quiet_validate_keeps_only_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "o.poscar"
    report = tmp_path / "r.json"
    assert (
        main(["convert", CO, "--to", "poscar", "-o", str(out), "--report", str(report), "-q"])
        == EXIT_OK
    )
    capsys.readouterr()
    rc = main(
        [
            "validate",
            "--source",
            CO,
            "--output",
            str(out),
            "--conversion-report",
            str(report),
            "-q",
        ]
    )
    assert rc == EXIT_OK
    assert capsys.readouterr().out == ""


def test_quiet_and_verbose_together_are_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["convert", CO, "--to", "poscar", "-q", "-v"])
    assert excinfo.value.code == EXIT_USAGE


def test_verbose_prints_stages_to_stderr_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "o.poscar"
    assert main(["convert", CO, "--to", "poscar", "-o", str(out), "-v"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "parsed as extxyz" in captured.err
    assert "conversion: completed" in captured.err
    assert "exported to" in captured.err
    assert "parsed as" not in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        ["inspect", CO],
        ["convert", CO, "--to", "poscar"],
        ["validate"],
        ["analyze", CO, "--plugin", "composition"],
        ["capabilities"],
    ],
)
def test_the_flags_exist_on_every_subcommand(argv: list[str]) -> None:
    parser = cli_main._build_parser()
    assert parser.parse_args([*argv, "-q"]).quiet is True
    assert parser.parse_args([*argv, "--verbose"]).verbose is True


def test_quiet_leaves_inspect_and_capabilities_output_alone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["capabilities", "-q"]) == EXIT_OK
    assert capsys.readouterr().out != ""  # the output *is* the result


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_progress_writes_on_a_tty_and_clears_its_line() -> None:
    tty = _FakeTTY()
    ticks = iter([0.0, 0.1, 0.3, 0.31])
    with _Progress(stream=tty, clock=lambda: next(ticks)) as progress:
        for n in range(1, 5):
            progress(n)
    text = tty.getvalue()
    assert text.startswith("\r1 frames") and "\r3 frames" in text
    assert "2 frames" not in text and "4 frames" not in text  # throttled away
    assert text.endswith("\r") and text.split("\r")[-2].strip() == ""


def test_progress_is_silent_when_not_a_tty() -> None:
    plain = io.StringIO()
    with _Progress(stream=plain) as progress:
        progress(10)
    assert plain.getvalue() == ""


def test_progress_is_silent_when_disabled() -> None:
    tty = _FakeTTY()
    with _Progress(stream=tty, enabled=False) as progress:
        progress(5)
    assert tty.getvalue() == ""


def test_progress_throttles_to_about_four_hertz() -> None:
    tty = _FakeTTY()
    ticks = iter([0.01 * i for i in range(50)])
    with _Progress(stream=tty, clock=lambda: next(ticks)) as progress:
        for n in range(1, 50):
            progress(n)
    assert tty.getvalue().count("frames") <= 3


def test_streamed_convert_passes_progress_to_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI wires `_Progress` into the streamed path (extxyz -> extxyz streams)."""
    seen: list[Any] = []
    real = cli_main.ConversionEngine.convert_stream

    def spy(self: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("progress"))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(cli_main.ConversionEngine, "convert_stream", spy)
    out = tmp_path / "o.extxyz"
    assert main(["convert", CO, "--to", "extxyz", "-o", str(out), "-q"]) == EXIT_OK
    assert len(seen) == 1 and callable(seen[0])


def test_autocomplete_is_a_no_op_when_the_extra_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "argcomplete", None)  # `import argcomplete` -> ImportError
    cli_main._maybe_autocomplete(cli_main._build_parser())  # must not raise


def test_autocomplete_is_hooked_when_the_extra_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    fake = types.ModuleType("argcomplete")
    fake.autocomplete = calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "argcomplete", fake)
    parser = cli_main._build_parser()
    cli_main._maybe_autocomplete(parser)
    assert calls == [parser]
