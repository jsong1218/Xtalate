"""The M12 memory proof (deliverable 7; the milestone's go/no-go gate).

Converts a large synthetic multi-frame extXYZ *through the streaming path* and asserts its peak RSS
stays well under what whole-file materialization demonstrably uses on the same input — the concrete
form of R8's mitigation (Part 10 §3): memory is sub-linear in frames, ``∝ chunk size × atoms``, not
``∝ frames``. The two modes run in separate subprocesses (``_mem_probe``) because ``ru_maxrss`` is a
non-decreasing high-water mark; a baseline subprocess isolates the interpreter+imports floor.

The thresholds are deliberately loose relative to the observed contrast (streaming holds one frame,
materialization the whole trajectory — a >10× gap in practice) so the gate is robust to CI noise
while still failing loudly if streaming ever regresses to materialize-then-write.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.streaming._generators import write_extxyz_trajectory

_N_FRAMES = 2500
_N_ATOMS = 50


def _probe(mode: str, *args: str) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "tests.streaming._mem_probe", mode, *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    return int(proc.stdout.strip().splitlines()[-1])


def test_streaming_conversion_is_sublinear_in_frames(tmp_path: Path) -> None:
    src = write_extxyz_trajectory(tmp_path / "traj.xyz", n_frames=_N_FRAMES, n_atoms=_N_ATOMS)
    out_stream = tmp_path / "out_stream.xyz"
    out_material = tmp_path / "out_material.xyz"

    baseline = _probe("baseline")
    stream_peak = _probe("stream", str(src), str(out_stream))
    material_peak = _probe("materialize", str(src), str(out_material))

    stream_delta = stream_peak - baseline
    material_delta = material_peak - baseline

    # The streaming path and whole-file path must agree on the *output* (chunking changes memory,
    # never bytes) — the honest anchor for the memory claim.
    assert out_stream.read_bytes() == out_material.read_bytes()

    # The core claim: materialization's peak substantially exceeds streaming's on the same file.
    assert material_peak > stream_peak * 1.3, (
        f"expected materialization peak >> streaming peak; "
        f"stream={stream_peak} material={material_peak} baseline={baseline}"
    )
    # And the trajectory-attributable memory of the streaming path is a small fraction of the
    # materialized path's — the sub-linear-in-frames property made numeric.
    assert material_delta > 0
    assert stream_delta < material_delta * 0.3, (
        f"streaming trajectory memory not a small fraction of materialized; "
        f"stream_delta={stream_delta} material_delta={material_delta}"
    )
