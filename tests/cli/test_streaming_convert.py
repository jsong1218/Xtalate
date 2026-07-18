"""CLI streaming routing (post-v0.3 architectural review, DECISIONS.md D63).

``xtalate convert`` routes eligible invocations through the streaming engines
(``convert_stream`` / ``convert_stream_select``) so the CLI inherits the library's sub-linear
memory. The contract pinned here: which path ran is **not observable** — output bytes and the
Conversion Report are identical to the materialized path (M12 standing rule 3) — the streaming
path genuinely runs for eligible pairs, ineligible invocations still materialize, and a
mid-stream parse error leaves no partial artifact behind.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_PARSE_ERROR, main
from xtalate.conversion.engine import ConversionEngine

# ``xtalate.cli`` re-exports the ``main`` *function*, which shadows the ``main`` module under
# ``import xtalate.cli.main as ...`` — resolve the module object explicitly to monkeypatch it.
cli_main = importlib.import_module("xtalate.cli.main")

XDATCAR = b"""NaCl MD run
   1.0
     5.6 0.0 0.0
     0.0 5.6 0.0
     0.0 0.0 5.6
   Na Cl
   1 1
Direct configuration=     1
  0.0 0.0 0.0
  0.5 0.5 0.5
Direct configuration=     2
  0.1 0.0 0.0
  0.5 0.5 0.5
Direct configuration=     3
  0.2 0.0 0.0
  0.5 0.5 0.5
"""

TRUNCATED_XDATCAR = XDATCAR[: XDATCAR.rfind(b"Direct configuration") + 40]

POSCAR = b"""single structure
1.0
  4.0 0.0 0.0
  0.0 4.0 0.0
  0.0 0.0 4.0
Si
2
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
"""


def _norm(report_path: Path) -> dict[str, Any]:
    d: dict[str, Any] = json.loads(report_path.read_text())
    d["report_id"] = "X"
    d["created_at"] = "X"
    return d


def _convert(src: Path, out: Path, *extra: str) -> int:
    report = out.with_suffix(".report.json")
    return main(
        ["convert", str(src), "--to", out.suffix.lstrip("."), "-o", str(out)]
        + ["--report", str(report)]
        + list(extra)
    )


def _force_materialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_main, "_convert_streamed", lambda args, registry: None)


@pytest.mark.parametrize(
    "extra",
    [(), ("--recover", "frame_selection=last")],
    ids=["convert_stream", "convert_stream_select"],
)
def test_streamed_cli_run_is_indistinguishable_from_materialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: tuple[str, ...]
) -> None:
    """The load-bearing property (M12 standing rule 3, now at the CLI surface): byte-identical
    output artifact and an identical Conversion Report, whichever engine path ran. The
    frame_selection variant exercises ``convert_stream_select`` (XDATCAR → POSCAR, D56's worked
    case); the plain variant exercises ``convert_stream`` (XDATCAR → extXYZ)."""
    src = tmp_path / "XDATCAR"
    src.write_bytes(XDATCAR)
    suffix = ".poscar" if extra else ".extxyz"
    streamed_dir, materialized_dir = tmp_path / "streamed", tmp_path / "materialized"
    streamed_dir.mkdir()
    materialized_dir.mkdir()
    out_streamed = streamed_dir / f"out{suffix}"
    out_materialized = materialized_dir / f"out{suffix}"

    assert _convert(src, out_streamed, *extra) == EXIT_OK

    _force_materialized(monkeypatch)
    assert _convert(src, out_materialized, *extra) == EXIT_OK

    assert out_streamed.read_bytes() == out_materialized.read_bytes()
    assert _norm(out_streamed.with_suffix(".report.json")) == _norm(
        out_materialized.with_suffix(".report.json")
    )


def test_eligible_pair_actually_takes_the_streaming_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards against the routing silently falling back for its flagship case: if the
    materialized ``convert`` runs at all, this fails."""

    def no_materialized(self: Any, *a: Any, **k: Any) -> Any:
        raise AssertionError("materialized convert() used for a streaming-eligible pair")

    monkeypatch.setattr(ConversionEngine, "convert", no_materialized)
    src = tmp_path / "XDATCAR"
    src.write_bytes(XDATCAR)
    assert _convert(src, tmp_path / "out.extxyz") == EXIT_OK


def test_ineligible_invocations_still_materialize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-streaming source (POSCAR), and a streaming pair without ``-o``, both keep the
    materialized path: if a streaming engine runs, this fails."""

    def no_streaming(self: Any, *a: Any, **k: Any) -> Any:
        raise AssertionError("streaming engine used for an ineligible invocation")

    monkeypatch.setattr(ConversionEngine, "convert_stream", no_streaming)
    monkeypatch.setattr(ConversionEngine, "convert_stream_select", no_streaming)

    src = tmp_path / "POSCAR"
    src.write_bytes(POSCAR)
    assert _convert(src, tmp_path / "out.extxyz") == EXIT_OK

    xdatcar = tmp_path / "XDATCAR"
    xdatcar.write_bytes(XDATCAR)
    report = tmp_path / "no_output.report.json"
    assert main(["convert", str(xdatcar), "--to", "extxyz", "--report", str(report)]) == EXIT_OK


def test_mid_stream_parse_error_leaves_no_partial_artifact(tmp_path: Path) -> None:
    """A truncated XDATCAR fails mid-stream on the streaming path. The pre-existing file at
    ``-o`` must survive untouched and no temp debris may remain — matching the materialized
    path, which writes the artifact only after the whole conversion succeeded."""
    src = tmp_path / "XDATCAR"
    src.write_bytes(TRUNCATED_XDATCAR)
    out = tmp_path / "out.extxyz"
    out.write_bytes(b"previous artifact\n")

    assert _convert(src, out) == EXIT_PARSE_ERROR
    assert out.read_bytes() == b"previous artifact\n"
    assert list(tmp_path.glob("*.partial")) == []


def test_parse_time_recovery_preset_materializes_and_recovers(tmp_path: Path) -> None:
    """A non-frame_selection preset (the XDATCAR ``truncate`` recovery) is out of the streaming
    path's scope; the invocation falls back and the recovery still works end to end."""
    src = tmp_path / "XDATCAR"
    src.write_bytes(TRUNCATED_XDATCAR)
    out = tmp_path / "out.extxyz"
    assert _convert(src, out, "--recover", "truncate_corrupt_tail=truncate") == EXIT_OK
    assert out.is_file() and out.stat().st_size > 0
