"""``xtalate analyze`` — the CLI mirror of the analysis surface (v1.8 M70, Appendix A).

The CLI runs one installed analysis plugin against a file and renders the namespaced results it
wrote (or emits them verbatim under ``--json``), exactly as ``POST /v1/analyze`` does over HTTP —
one engine (:func:`xtalate.sdk.run_analysis`), two presenters. The plain dev gate installs no
analysis plugin (the composition reference plugin ships as its own distribution), so these tests
inject their own plugins through the entry-point discovery seam — a well-behaved one that writes its
own namespace, and a rogue one that escapes it — and pin the four outcomes: a rendered report, the
``--json`` parity, an unknown plugin (a clean usage error listing the installed set), and a plugin
that breaks containment (an :class:`~xtalate.sdk.AnalysisError`, exit 1).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import JsonValue

import xtalate.registry as registry_mod
from tests._fake_entry_points import FakeEntryPoint, patch_entry_points
from xtalate.cli.main import EXIT_OK, EXIT_PARSE_ERROR, EXIT_USAGE, main
from xtalate.sdk import AnalysisPlugin

if TYPE_CHECKING:
    from xtalate.schema import CanonicalObject

WATER = str(Path(__file__).parent.parent / "golden" / "xyz" / "water-traj" / "water_traj.xyz")


def _hill(symbols: list[str]) -> str:
    """Hill order: carbon, then hydrogen, then every other element alphabetically."""
    counts = Counter(symbols)

    def token(sym: str) -> str:
        return sym + (str(counts[sym]) if counts[sym] > 1 else "")

    ordered = [s for s in ("C", "H") if s in counts]
    ordered += sorted(s for s in counts if s not in ("C", "H"))
    return "".join(token(s) for s in ordered)


class _FormulaPlugin(AnalysisPlugin):
    """A well-behaved plugin: writes only its own ``formula:`` namespace (Part 2 §6 rule 2)."""

    name = "formula"
    version = "2.0.0"

    def analyze(self, canonical: CanonicalObject) -> Mapping[str, JsonValue]:
        symbols = list(canonical.frames[0].atoms.symbols)
        return {"formula:hill": _hill(symbols), "formula:atom_count": len(symbols)}


class _RoguePlugin(AnalysisPlugin):
    """A misbehaving plugin: writes a key outside its own namespace → :class:`AnalysisError`."""

    name = "rogue"
    version = "0.1.0"

    def analyze(self, canonical: CanonicalObject) -> Mapping[str, JsonValue]:
        return {"other:leak": 1}


def _install(monkeypatch: pytest.MonkeyPatch, *plugins: AnalysisPlugin) -> None:
    """Route entry-point discovery to exactly ``plugins`` (deterministic across CI and a local
    editable install of the composition reference plugin — the phantom-install footgun)."""
    eps = [
        FakeEntryPoint(
            p.name,
            f"test_dist:{type(p).__name__}",
            registry_mod.ANALYSIS_ENTRY_POINT_GROUP,
            lambda p=p: p,
        )
        for p in plugins
    ]
    patch_entry_points(monkeypatch, analysis=eps)


def test_analyze_renders_the_namespaced_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, _FormulaPlugin())
    assert main(["analyze", WATER, "--plugin", "formula"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "formula:hill" in out
    assert "H2O" in out


def test_analyze_json_emits_plugin_version_and_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, _FormulaPlugin())
    assert main(["analyze", WATER, "--plugin", "formula", "--json"]) == EXIT_OK
    data = json.loads(capsys.readouterr().out)
    assert data["plugin"] == "formula"
    assert data["version"] == "2.0.0"
    # Exactly the plugin's own namespace, verbatim — the keys it wrote into custom_global.
    assert data["results"] == {"formula:hill": "H2O", "formula:atom_count": 3}


def test_analyze_unknown_plugin_lists_the_installed_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install(monkeypatch, _FormulaPlugin())
    assert main(["analyze", WATER, "--plugin", "nope"]) == EXIT_USAGE
    err = capsys.readouterr().err
    # The installed set is named so the caller can correct the request without a second guess.
    assert "formula" in err
    assert "nope" in err


def test_analyze_plugin_breaking_containment_is_a_clean_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A plugin that escapes its namespace raises AnalysisError — a broken plugin, not a graceful
    # refusal: a clean stderr message naming it and exit 1, never a traceback.
    _install(monkeypatch, _RoguePlugin())
    assert main(["analyze", WATER, "--plugin", "rogue"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "rogue" in err
    assert "Traceback" not in err


def test_analyze_unparseable_file_is_a_parse_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install(monkeypatch, _FormulaPlugin())
    junk = tmp_path / "junk.xyz"
    junk.write_text("not a molecule in any known format\n")
    assert main(["analyze", str(junk), "--plugin", "formula"]) == EXIT_PARSE_ERROR
