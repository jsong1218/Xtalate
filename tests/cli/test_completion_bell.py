"""CLI completion-bell tests (v1.1 M39-S4, C2).

`xtalate convert` rings the terminal bell (``\\a``) on **stderr** when it finishes — a converted
file *or* a refusal — but only when stderr is a TTY and the user has not opted out (``--no-bell``
or ``XTALATE_NO_BELL``). These pin the four gates: bell on a TTY (both terminal outcomes),
suppressed by the flag, suppressed by the env var, and never on a piped/redirected stream. The
bell is asserted on captured stderr — stdout stays the clean machine-facing surface.

The fake stderr is installed **inside each test body**: pytest's per-test capture re-installs its
own `sys.stderr` *after* fixtures run, so a monkeypatch applied in a fixture would be clobbered
before the test body executes.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_REFUSED, main

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = str(GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")

_RECOVER = [
    "--recover",
    "frame_selection=last",
    "--recover",
    "missing_lattice=bounding_box,padding_ang=5.0",
]


class _FakeStderr:
    """A stand-in for ``sys.stderr`` with a controllable ``isatty`` and a capture buffer."""

    def __init__(self, *, tty: bool) -> None:
        self._tty = tty
        self.buffer = io.StringIO()

    def isatty(self) -> bool:
        return self._tty

    def write(self, text: str) -> int:
        return self.buffer.write(text)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self.buffer.getvalue()


def _tty_stderr(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> _FakeStderr:
    fake = _FakeStderr(tty=tty)
    monkeypatch.setattr(sys, "stderr", fake)
    return fake


def _convert_args(tmp_path: Path, *extra: str) -> list[str]:
    return ["convert", WATER, "--to", "poscar", "-o", str(tmp_path / "POSCAR"), *extra]


def test_bell_rings_on_a_tty_when_the_conversion_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stderr = _tty_stderr(monkeypatch, tty=True)
    assert main(_convert_args(tmp_path, *_RECOVER)) == EXIT_OK
    assert "\a" in stderr.getvalue()


def test_bell_rings_on_a_tty_for_a_refusal_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A refusal is a terminal outcome — the bell says "it's done", the report says "refused".
    stderr = _tty_stderr(monkeypatch, tty=True)
    assert main(_convert_args(tmp_path)) == EXIT_REFUSED
    assert "\a" in stderr.getvalue()


def test_no_bell_flag_suppresses_the_bell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = _tty_stderr(monkeypatch, tty=True)
    assert main(_convert_args(tmp_path, *_RECOVER, "--no-bell")) == EXIT_OK
    assert "\a" not in stderr.getvalue()


def test_xtalate_no_bell_env_var_suppresses_the_bell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stderr = _tty_stderr(monkeypatch, tty=True)
    monkeypatch.setenv("XTALATE_NO_BELL", "1")
    assert main(_convert_args(tmp_path, *_RECOVER)) == EXIT_OK
    assert "\a" not in stderr.getvalue()


def test_no_bell_when_stderr_is_not_a_tty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = _tty_stderr(monkeypatch, tty=False)
    assert main(_convert_args(tmp_path, *_RECOVER)) == EXIT_OK
    # The stream is piped/redirected: no control byte ever lands in it.
    assert "\a" not in stderr.getvalue()
