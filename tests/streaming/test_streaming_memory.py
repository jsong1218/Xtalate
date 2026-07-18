"""The M12 memory proof (deliverable 7; the milestone's go/no-go gate).

Converts a large synthetic multi-frame trajectory *through the streaming path* and asserts the
Python-heap memory the conversion allocates stays a small fraction of what whole-file
materialization demonstrably uses on the same input — the concrete form of R8's mitigation
(Part 10 §3): memory is sub-linear in frames, ``∝ chunk size × atoms``, not ``∝ frames``.

**Why ``tracemalloc``, not peak RSS.** An earlier form of this gate compared ``ru_maxrss`` between
subprocesses. ``ru_maxrss`` is a whole-process high-water mark that never falls, so it also captures
the *import* transient — and on Linux/glibc the scientific stack (numpy + ASE + pydantic) peaks well
above 150 MB while importing and never releases it back to the high-water mark. A conversion whose
own footprint is real but smaller than that import transient (XDATCAR materialize, ≈50 MB) then
shows up as *zero* delta, because its allocations reuse pages already counted at import. That made
the gate silently input-dependent: the extXYZ proof (≈90 MB materialized) cleared the import floor
and passed, the XDATCAR proof did not. ``tracemalloc.reset_peak()`` discards the import high-water
mark and measures only the memory the conversion itself allocates, so the two paths separate by
~50–200× on every platform. It traces the Python heap (the ``Frame``/``AtomsBlock``/``Cell`` objects
the streaming path avoids holding all at once) but not numpy's C data buffers; those grow with frame
count in the same direction, so excluding them only makes the demonstrated contrast a conservative
lower bound on the true footprint gap — never an overstatement.
"""

from __future__ import annotations

import gc
import tracemalloc
from collections.abc import Callable
from pathlib import Path

from tests.streaming._generators import (
    write_ase_traj_trajectory,
    write_extxyz_trajectory,
    write_xdatcar_trajectory,
)
from xtalate.registry import default_registry
from xtalate.sdk.streaming import export_stream

_N_FRAMES = 2500
_N_ATOMS = 50


def _peak_traced_bytes(fn: Callable[[], None]) -> int:
    """Peak Python-heap bytes allocated *during* ``fn`` — the import floor excluded.

    ``reset_peak`` is the whole point: it zeroes the high-water mark after everything is imported
    and the fixture is on disk, so the number reflects the conversion's own allocations, not the
    interpreter+imports floor a whole-process RSS reading would fold in.
    """
    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def _stream(src: Path, out: Path, source_format: str, target_format: str) -> None:
    registry = default_registry()
    parser = registry.get_parser(source_format)
    exporter = registry.get_exporter(target_format)
    with src.open("rb") as fh:
        # Hand the parser the open file directly so it never slurps the whole trajectory into one
        # string — the strongest memory bound.
        stream = parser.parse_stream(fh, filename=src.name)
        with out.open("wb") as out_fh:
            export_stream(exporter, stream.header, stream.frames(), out_fh)


def _materialize(src: Path, out: Path, source_format: str, target_format: str) -> None:
    import io

    registry = default_registry()
    parser = registry.get_parser(source_format)
    exporter = registry.get_exporter(target_format)
    data = src.read_bytes()
    canonical = parser.parse(io.BytesIO(data), filename=src.name).canonical
    buf = io.BytesIO()
    exporter.export(canonical, buf)
    out.write_bytes(buf.getvalue())


def _assert_sublinear(
    stream_peak: int, material_peak: int, out_stream: Path, out_material: Path
) -> None:
    # The streaming path and whole-file path must agree on the *output* (chunking changes memory,
    # never bytes) — the honest anchor for the memory claim.
    assert out_stream.read_bytes() == out_material.read_bytes()

    # Materialization holds the whole trajectory (all _N_FRAMES pydantic frames + arrays) at once,
    # so its Python-heap footprint is a clear, measurable tens-of-MB (≈47 MB for XDATCAR, ≈90 MB
    # for extXYZ). This floor is generous relative to both and platform-independent — Python object
    # sizes don't vary by OS, and tracemalloc excludes the import transient that swamped the signal.
    assert material_peak > 10 * 1024 * 1024, (
        f"materialization footprint unexpectedly small; material_peak={material_peak} "
        f"(stream={stream_peak})"
    )
    # Streaming holds ~one frame, so its footprint is a small fraction of the materialized one —
    # the sub-linear-in-frames property. A regression to materialize-then-write would push
    # stream_peak toward material_peak and trip this. Observed gap ~50–200×; ``× 4`` keeps a margin.
    assert stream_peak * 4 < material_peak, (
        f"streaming footprint not a small fraction of materialized; "
        f"stream_peak={stream_peak} material_peak={material_peak}"
    )


def test_streaming_conversion_is_sublinear_in_frames(tmp_path: Path) -> None:
    src = write_extxyz_trajectory(tmp_path / "traj.xyz", n_frames=_N_FRAMES, n_atoms=_N_ATOMS)
    out_stream = tmp_path / "out_stream.xyz"
    out_material = tmp_path / "out_material.xyz"

    stream_peak = _peak_traced_bytes(lambda: _stream(src, out_stream, "extxyz", "extxyz"))
    material_peak = _peak_traced_bytes(lambda: _materialize(src, out_material, "extxyz", "extxyz"))
    _assert_sublinear(stream_peak, material_peak, out_stream, out_material)


def test_xdatcar_conversion_is_sublinear_in_frames(tmp_path: Path) -> None:
    """The honest M13 gate: XDATCAR is the format whose ordinary size is a full MD trajectory, so
    converting one to extXYZ must stay bounded by a single frame. Same contrast as the extXYZ proof,
    driven through the XDATCAR streaming parser (Part 4 §6, R8; DECISIONS.md D56)."""
    src = write_xdatcar_trajectory(tmp_path / "XDATCAR", n_frames=_N_FRAMES, n_atoms=_N_ATOMS)
    out_stream = tmp_path / "xdatcar_stream.xyz"
    out_material = tmp_path / "xdatcar_material.xyz"

    stream_peak = _peak_traced_bytes(lambda: _stream(src, out_stream, "xdatcar", "extxyz"))
    material_peak = _peak_traced_bytes(lambda: _materialize(src, out_material, "xdatcar", "extxyz"))
    _assert_sublinear(stream_peak, material_peak, out_stream, out_material)


def test_ase_traj_conversion_is_sublinear_in_frames(tmp_path: Path) -> None:
    """The M14E gate: ASE ``.traj`` is the richest Phase-1 format and its own binary container, so
    proving its streaming path holds one frame — not the frame count — is what lets M14 claim the
    ASE parser is genuinely frame-lazy (its ``TrajectoryReader`` gives random access from the open
    file). Same contrast as the extXYZ/XDATCAR proofs, driven through the ASE-traj streaming parser
    (Part 4 §5; M14 deliverable)."""
    src = write_ase_traj_trajectory(tmp_path / "relax.traj", n_frames=_N_FRAMES, n_atoms=_N_ATOMS)
    out_stream = tmp_path / "ase_traj_stream.xyz"
    out_material = tmp_path / "ase_traj_material.xyz"

    stream_peak = _peak_traced_bytes(lambda: _stream(src, out_stream, "ase_traj", "extxyz"))
    material_peak = _peak_traced_bytes(
        lambda: _materialize(src, out_material, "ase_traj", "extxyz")
    )
    _assert_sublinear(stream_peak, material_peak, out_stream, out_material)
