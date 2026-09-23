"""End-to-end proof of a *third-party analysis plugin* built from the docs alone (v1.8 M71).

``tests/sdk/test_analysis.py`` proves the runner's containment and provenance guarantees against
an in-tree toy plugin; ``tests/test_toyfmt_plugin.py`` proves entry-point discovery of a parser +
exporter against a real installed distribution. This module closes the last gap for the analysis
plugin kind: an actual installable package, ``tests/fixtures/xtalate_toyanalysis``, written from
``docs/DEVELOPER_GUIDE.md`` §8 against only the frozen public SDK — no core edits, no copy of the
first-party reference plugin. When it is pip-installed, its plugin must be

* **discovered** in ``default_registry().analysis_plugins()`` (the ``xtalate.analysis`` entry-point
  group, resolved from real dist-info), additively — the reference plugin and built-ins untouched;
* **run and contained** — ``run_analysis`` merges only its ``"toyanalysis:"`` keys into
  ``user_metadata.custom_global``, appends exactly one ``operation="analyze"`` record, and leaves
  the caller's object untouched (D268/D269);
* **absence-honest** — cell volume is a real number when the source carries a cell and ``None``
  with a stated reason when it does not (§8.3, P3/P4); and
* **rendered on a real consumer surface** — ``xtalate analyze FILE --plugin toyanalysis --json``,
  in a fresh subprocess, resolves the plugin from installed dist-info and prints its keys.

The fixture is installed by CI (`pip install --no-deps ./tests/fixtures/xtalate_toyanalysis`);
these tests **skip** when it is absent, so a plain local checkout stays green. To run them locally:

    pip install --no-deps ./tests/fixtures/xtalate_toyanalysis
"""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import xtalate
from xtalate.registry import default_registry
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    ConversionRecord,
    Frame,
    Provenance,
    UserMetadata,
)
from xtalate.sdk import AnalysisPlugin, run_analysis

_DISTRIBUTION = "xtalate-toyanalysis"
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "xtalate_toyanalysis"


def _toyanalysis_installed() -> bool:
    try:
        importlib_metadata.distribution(_DISTRIBUTION)
    except importlib_metadata.PackageNotFoundError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _toyanalysis_installed(),
    reason=(
        f"{_DISTRIBUTION} not installed; run "
        f"`pip install --no-deps ./{_FIXTURE_DIR.as_posix()}` (CI installs it before pytest)"
    ),
)


def _obj(*, with_cell: bool) -> CanonicalObject:
    """A two-atom object, optionally with a 3 Å cubic cell (volume 27 Å³), carrying a prior
    carry-through key and history record so the merge and append run against real content."""
    atoms = AtomsBlock(
        symbols=["O", "H"],
        positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
    )
    cell = Cell(lattice_vectors=np.eye(3) * 3.0, pbc=(True, True, True)) if with_cell else None
    return CanonicalObject(
        frames=[Frame(index=0, atoms=atoms, cell=cell)],
        provenance=Provenance(
            source_filename="water.xyz",
            source_format="xyz",
            source_units={"positions": "angstrom"},
            original_coordinate_system="cartesian",
            history=[
                ConversionRecord(
                    timestamp="2026-09-13T00:00:00Z",
                    operation="parse",
                    source_format="xyz",
                    target_format=None,
                    tool_version=xtalate.__version__,
                    parser_version=f"xyz-parser {xtalate.__version__}",
                    assumptions=[],
                )
            ],
        ),
        user_metadata=UserMetadata(custom_global={"xyz:comment": "from the source file"}),
    )


def _plugin() -> AnalysisPlugin:
    installed = {p.name: p for p in default_registry().analysis_plugins()}
    assert "toyanalysis" in installed, "toyanalysis not discovered in the registry"
    return installed["toyanalysis"]


def test_toyanalysis_is_discovered_additively() -> None:
    """The installed third-party plugin joins the roster without displacing the first-party
    reference plugin (M69) — additive discovery, P6."""
    names = {p.name for p in default_registry().analysis_plugins()}
    assert "toyanalysis" in names
    assert "composition" in names  # the reference plugin is untouched


def test_run_analysis_merges_only_the_namespace_and_records_once() -> None:
    """The docs' namespace + provenance contract (§8.2), proven on the installed plugin: only
    ``toyanalysis:`` keys land in ``custom_global``, exactly one ``analyze`` record is appended,
    and the caller's object is untouched (D268/D269)."""
    source = _obj(with_cell=True)
    before_history = len(source.provenance.history)

    run = run_analysis(source, _plugin())
    annotated = run.canonical

    written = run.entries
    assert set(written) == {
        "toyanalysis:frame_count",
        "toyanalysis:atom_count",
        "toyanalysis:distinct_elements",
        "toyanalysis:cell_volume_a3",
        "toyanalysis:cell_volume_note",
    }
    assert written["toyanalysis:frame_count"] == 1
    assert written["toyanalysis:atom_count"] == 2
    assert written["toyanalysis:distinct_elements"] == ["H", "O"]
    assert written["toyanalysis:cell_volume_a3"] == pytest.approx(27.0)

    # The pre-existing carry-through key survives; exactly one analyze record is appended.
    assert annotated.user_metadata.custom_global["xyz:comment"] == "from the source file"
    assert len(annotated.provenance.history) == before_history + 1
    record = annotated.provenance.history[-1]
    assert record.operation == "analyze"
    assert record.parser_version == "toyanalysis 1.0.0"

    # The caller's object is untouched — analysis is annotation, never mutation (D268).
    assert source.user_metadata.custom_global == {"xyz:comment": "from the source file"}
    assert len(source.provenance.history) == before_history


def test_toyanalysis_reports_absent_cell_volume_honestly() -> None:
    """§8.3/P3/P4 on the installed plugin: with a cell, a real number; without one, ``None``
    paired with a plain-language reason — never a fabricated volume."""
    with_cell = run_analysis(_obj(with_cell=True), _plugin()).entries
    assert with_cell["toyanalysis:cell_volume_a3"] == pytest.approx(27.0)
    with_note = with_cell["toyanalysis:cell_volume_note"]
    assert isinstance(with_note, str) and "computed" in with_note

    without_cell = run_analysis(_obj(with_cell=False), _plugin()).entries
    assert without_cell["toyanalysis:cell_volume_a3"] is None
    without_note = without_cell["toyanalysis:cell_volume_note"]
    assert isinstance(without_note, str) and "no simulation cell" in without_note


def test_cli_analyze_renders_the_third_party_plugin(tmp_path: Path) -> None:
    """The consumer surface, resolved from installed dist-info: ``xtalate analyze --plugin
    toyanalysis --json`` in a fresh subprocess renders the plugin's keys. A cell-less XYZ source
    proves the honest ``null`` volume travels all the way to the rendered output (generic UI
    rendering of the same keys is proven on the reference plugin by M70's e2e)."""
    source = tmp_path / "water.xyz"
    source.write_text("2\nwater\nO 0.0 0.0 0.0\nH 0.9584 0.0 0.0\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from xtalate.cli import main; sys.exit(main(sys.argv[1:]))",
            "analyze",
            str(source),
            "--plugin",
            "toyanalysis",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["plugin"] == "toyanalysis"
    assert payload["version"] == "1.0.0"
    results = payload["results"]
    assert results["toyanalysis:atom_count"] == 2
    assert results["toyanalysis:distinct_elements"] == ["H", "O"]
    # A plain XYZ file carries no cell, so the volume is an honest null, not a fabricated number.
    assert results["toyanalysis:cell_volume_a3"] is None
