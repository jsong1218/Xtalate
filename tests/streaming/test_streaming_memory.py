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

    # Compare *trajectory-attributable* memory — peak minus the interpreter+imports floor — not
    # absolute peaks. On CI the import baseline (~150 MB) dominates the peak and swamps the signal:
    # the streaming path can add ~0 measurable RSS (a great result) while materialization adds tens
    # of MB, yet the two *absolute* peaks then sit within ~25% of each other. The honest claim is
    # about the deltas. A subprocess measuring below the separately-probed baseline is clamped to 0.
    stream_delta = max(0, stream_peak - baseline)
    material_delta = material_peak - baseline

    # The streaming path and whole-file path must agree on the *output* (chunking changes memory,
    # never bytes) — the honest anchor for the memory claim.
    assert out_stream.read_bytes() == out_material.read_bytes()

    # Materialization holds the whole trajectory (all _N_FRAMES pydantic frames + arrays) at once,
    # so its footprint is a clear, measurable tens-of-MB (≈34 MB on CI, ≈120 MB locally). This floor
    # is generous relative to both, and OS-independent — Python object sizes don't vary by platform.
    assert material_delta > 10 * 1024 * 1024, (
        f"materialization footprint unexpectedly small; material_delta={material_delta} "
        f"(stream={stream_peak} material={material_peak} baseline={baseline})"
    )
    # Streaming holds ~one frame, so its footprint is at most a small fraction of the materialized
    # one — the sub-linear-in-frames property. A regression to materialize-then-write would push
    # stream_delta up toward material_delta and trip this.
    assert stream_delta * 2 < material_delta, (
        f"streaming footprint not a small fraction of materialized; "
        f"stream_delta={stream_delta} material_delta={material_delta} "
        f"(stream={stream_peak} material={material_peak} baseline={baseline})"
    )
