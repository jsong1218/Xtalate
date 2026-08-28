"""The flagship example cannot silently rot (the M36 canary discipline, applied to examples).

The M58-S3 stopping point is a runnable script — ``examples/batch_assemble_training_set.py``
converts a mixed VASP/QE/LAMMPS manifest of committed real fixtures into one assembled extXYZ
training set with a green aggregate record. This canary executes it **as a user would**
(subprocess, real interpreter, real fixtures, a temp output path) and pins the honest
statements it must keep making: every file converted and validated, and the dataset-level
mixed-composition note printed verbatim — an anomaly elided, or a report line that stops
printing, fails here.

The example is a demo script, not library code — coverage measures ``xtalate`` only, so the
canary's subprocess (which does not count toward coverage) cannot skew the 91% gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "batch_assemble_training_set.py"


def test_batch_assemble_example_runs_to_a_green_aggregate(tmp_path: Path) -> None:
    output = tmp_path / "training_set.extxyz"
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE), str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"example failed:\n{proc.stdout}\n{proc.stderr}"

    # The aggregate is green: all four sources converted, none refused or failed, every
    # per-file validation passed.
    assert "4 converted · 0 refused · 0 failed" in proc.stdout
    assert "converted [passed]" in proc.stdout

    # The sources differ in composition, so the assembled file is variable-N: the honest
    # dataset-level statement must be printed, never elided.
    assert "mixed-composition note:" in proc.stdout
    assert "EXTXYZ_VARIABLE_ATOM_COUNT" in proc.stdout

    # And the training set was actually written.
    assert output.is_file()
    assert output.stat().st_size > 0
    header = output.read_text(encoding="utf-8").splitlines()[0]
    assert header.isdigit() and int(header) >= 2
