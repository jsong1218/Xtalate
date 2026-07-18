"""The spec's flagship worked example, made executable (M14D; MASTER_SPEC Part 4 §5, Part 5 §6).

M14's milestone **exit door**: the ``relax.traj → POSCAR`` example the spec works by hand — an
isolated 3-atom water molecule, 10 frames, ASE default zero cell laundered to absence, converted
with ``frame_selection=last`` + ``missing_lattice=bounding_box`` — is driven end to end through the
real CLI, and both emitted reports are diffed **byte-for-byte** (modulo volatile ids/timestamps)
against fixtures derived from the spec's own JSON:

* the **Conversion Report** (Part 4 §5, lines 1903–1951) — preserved ``atoms.symbols`` /
  ``atoms.positions``; ``dynamics.forces`` + ``electronic.total_energy`` removed as unstorable and
  frames 0–8 removed for the single-structure target; ``cell.lattice_vectors`` + ``cell.pbc``
  *supplied* (not preserved) via Assumption A2; A1/A2 recorded;
* the **Validation Report** (Part 5 §6, lines 2154–2232) — the nine checks, ``passed``, with
  ``numeric_field_fidelity`` legitimately skipped and the fabricated lattice validated as rigorously
  as source data.

The fixtures carry ``<normalized>`` in the three non-deterministic slots (``report_id``,
``created_at``, and the validation report's ``conversion_report_id``, plus a defensively normalized
``source.sha256``); :func:`_normalized` stamps the same placeholder into the emitted reports before
the comparison, so everything *scientific* in the report must match exactly — a drift in any path,
reason, assumption, warning, or check is a failure. This is the guarantee the milestone tags on:
the worked example is not prose, it is a passing test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.cli._worked_example import write_relax_traj
from xtalate.cli.main import EXIT_OK, main
from xtalate.parsers.ase_traj import make_ase_traj_parser

FIXTURES = Path(__file__).parent / "worked_example"
_PLACEHOLDER = "<normalized>"


def _normalized(report: dict[str, Any]) -> dict[str, Any]:
    """Stamp the placeholder into every field that legitimately varies run to run — the UUIDs, the
    wall-clock timestamp, and (defensively) the source digest — so the diff is over scientific
    content only, matching how the committed fixtures were written."""
    for key in ("report_id", "created_at", "conversion_report_id"):
        if key in report:
            report[key] = _PLACEHOLDER
    if "source" in report and "sha256" in report["source"]:
        report["source"]["sha256"] = _PLACEHOLDER
    return report


def test_worked_example_source_matches_the_spec(tmp_path: Path) -> None:
    """Guard the fixture's premise (MASTER_SPEC line 1876): the generated source really is a
    10-frame trajectory whose ASE default zero cell launders to ``cell = None`` and which carries
    forces + energy but no velocities — the exact starting conditions the worked reports assume."""
    traj = write_relax_traj(tmp_path / "relax.traj")
    obj = make_ase_traj_parser().parse(traj.open("rb"), filename="relax.traj").canonical
    assert len(obj.frames) == 10
    frame = obj.frames[9]
    assert frame.cell is None  # ASE's zero cell laundered to absence (P3) — the missing_lattice gap
    assert frame.dynamics.forces is not None
    assert frame.electronic.total_energy is not None
    assert frame.dynamics.velocities is None


def test_worked_example_reports_match_spec_fixtures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    traj = write_relax_traj(tmp_path / "relax.traj")
    conv = tmp_path / "conversion.json"
    val = tmp_path / "validation.json"
    code = main(
        [
            "convert",
            str(traj),
            "--to",
            "poscar",
            "-o",
            str(tmp_path / "POSCAR"),
            "--recover",
            "frame_selection=last",
            "--recover",
            "missing_lattice=bounding_box,padding_ang=5.0",
            "--report",
            str(conv),
            "--validation-report",
            str(val),
        ]
    )
    assert code == EXIT_OK

    emitted_conv = _normalized(json.loads(conv.read_text()))
    emitted_val = _normalized(json.loads(val.read_text()))
    expected_conv = json.loads((FIXTURES / "conversion.expected.json").read_text())
    expected_val = json.loads((FIXTURES / "validation.expected.json").read_text())

    assert emitted_conv == expected_conv
    assert emitted_val == expected_val

    # The status contract the spec headlines: a completed conversion whose report validated clean.
    assert emitted_conv["status"] == "completed"
    assert emitted_val["status"] == "passed"
