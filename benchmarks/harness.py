"""The M15A synthetic performance corpus + benchmark harness (measured, not gated).

Turns the "large trajectory performance" risk (MASTER_SPEC Part 8 §4) into a tracked number
rather than an anecdote. Ten benchmarks reproduce the spec's performance table exactly:

* ``parse_xdatcar_10k`` — parse XDATCAR, 10,000 frames × 100 atoms — ≤ 30 s, peak RSS ≤ 2 GB.
* ``convert_xdatcar_to_extxyz_10k`` — full pipeline incl. validation, same file — ≤ 90 s, ≤ 2 GB.
* ``parse_vasprun_10k`` — parse vasprun.xml, 10,000 ionic steps × 100 atoms — ≤ 30 s, ≤ 2 GB.
* ``parse_outcar_10k`` — parse OUTCAR, 10,000 ionic steps × 100 atoms — ≤ 30 s, ≤ 2 GB.
* ``convert_outcar_to_extxyz_10k`` — the flagship VASP→MLIP conversion, same file — ≤ 90 s, ≤ 2 GB.
* ``parse_qeout_10k`` — parse a pw.x output, 10,000 ionic steps × 100 atoms (M52) — ≤ 30 s, ≤ 2 GB.
* ``convert_qeout_to_extxyz_10k`` — the QE→MLIP reference-data conversion, same file —
  ≤ 90 s, ≤ 2 GB.
* ``parse_lammpsdump_10k`` — parse a LAMMPS dump, 10,000 frames × 100 atoms — ≤ 30 s, ≤ 2 GB.
* ``convert_lammpsdump_to_extxyz_10k`` — the deployment-format→MLIP conversion, same file —
  ≤ 90 s, ≤ 2 GB.
* ``convert_extxyz_roundtrip_1k`` — extXYZ 1,000 × 1,000 identity round-trip — ≤ 60 s, ≤ 3 GB.
* ``frame_limit_ceiling`` — 100,000-frame file (the ``06 §5`` cap) — completes, sub-linear memory.
* ``preflight_latency`` — pre-flight diff on a parsed 10k-frame object — ≤ 1 s (feels instant).

**Measured, not gated (MASTER_SPEC Part 8 §4; the standing rule).** Shared CI runners make
per-PR timings noisy enough to false-fail weekly, so this harness *reports* wall-time and
peak-RSS series and flags whether each measurement is within its spec budget — it never exits
non-zero on a budget breach. A non-zero exit means a benchmark *crashed* (the harness itself is
broken), which is a real failure. The >20 % regression tripwire against a rolling median lives in
the nightly workflow on a pinned runner (M15C), where timings are comparable; it is deliberately
absent here.

**Subprocess per benchmark — the honest peak-RSS.** Peak RSS is read from
``resource.getrusage(RUSAGE_SELF).ru_maxrss``, a whole-process high-water mark that never falls.
Running two benchmarks in one interpreter would report the *second* one's peak as the max of both.
So each benchmark runs in its own ``python -m benchmarks _child …`` subprocess, which measures its
own wall time and peak RSS and writes them to a result file the parent reads back. (This is why the
in-test streaming gate uses ``tracemalloc`` instead — there the import floor must be excluded; here
whole-process peak RSS *is* the number the spec's "Peak RSS ≤ 2 GB" bound is written against.)

**Generated, never committed (MASTER_SPEC Part 8 §4).** The corpus is synthetic and reproduced
from the committed, seeded generators in ``tests/streaming/_generators.py`` — a 10,000-frame XDATCAR
need not be stored, only regenerated. Each benchmark writes its fixture into a private temp dir that
is removed afterwards.

**No new dependencies.** Standard library (``subprocess``/``resource``/``json``/``csv``) plus the
existing generators and the ``xtalate`` public API. Kept out of the coverage-gated pytest run
(``testpaths = ["tests"]``); run it explicitly with ``python -m benchmarks`` (or ``--smoke`` for a
fast micro-scale wiring check).
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import os
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from csv import writer as csv_writer
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.streaming._generators import (
    write_extxyz_trajectory,
    write_lammps_dump_trajectory,
    write_outcar_trajectory,
    write_qe_pw_out_trajectory,
    write_vasprun_trajectory,
    write_xdatcar_trajectory,
)

from benchmarks import tripwire
from xtalate.cli.main import EXIT_OK
from xtalate.cli.main import main as cli_main
from xtalate.conversion.batch import BatchManifest, run_batch
from xtalate.conversion.preflight import build_preflight
from xtalate.registry import default_registry
from xtalate.sdk.streaming import export_stream

_GiB = 1024**3

FULL = "full"
MICRO = "micro"


@dataclass(frozen=True)
class Scale:
    """A single ``n_frames × n_atoms`` sizing of a benchmark's synthetic fixture."""

    n_frames: int
    n_atoms: int


@dataclass(frozen=True)
class Budget:
    """A spec target: the value at ``metric`` must stay ``<= limit`` (measured, never enforced)."""

    metric: str
    limit: float
    unit: str  # "s" | "bytes"


@dataclass(frozen=True)
class Benchmark:
    """One row of the spec's performance table: a workload plus its (measured-only) budgets."""

    name: str
    run: Callable[[Path, str], dict[str, float]]
    budgets: tuple[Budget, ...]


def _sized(scale: str, *, full: Scale, micro: Scale) -> Scale:
    """Pick the spec-scale fixture for a real run, or a tiny one for a ``--smoke`` wiring check."""
    return full if scale == FULL else micro


def _cli_ok(argv: list[str]) -> None:
    """Drive the real ``xtalate`` CLI in-process, its own stdout/stderr swallowed so it cannot
    corrupt the child's result output. A non-``EXIT_OK`` code is a crash — raise so the benchmark
    fails loudly rather than reporting a bogus timing for a conversion that never happened."""
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        code = cli_main(argv)
    if code != EXIT_OK:
        raise RuntimeError(f"CLI exited {code} for argv={argv!r}\n{sink.getvalue()}")


def _bench_parse_xdatcar_10k(workdir: Path, scale: str) -> dict[str, float]:
    """Materialize a full 10k-frame XDATCAR — the ``∝ frames`` cost the ≤2 GB bound guards."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_xdatcar_trajectory(workdir / "XDATCAR", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    parser = default_registry().get_parser("xdatcar")
    with src.open("rb") as fh:
        obj = parser.parse(fh, filename=src.name).canonical
    return {"frames": float(obj.frame_count), "atoms": float(sz.n_atoms)}


def _bench_convert_xdatcar_to_extxyz_10k(workdir: Path, scale: str) -> dict[str, float]:
    """The full spine on the same 10k file: parse → convert → validate, via the real CLI. The
    ``--validation-report`` flag forces the post-conversion re-parse-and-diff, so this is the
    end-to-end pipeline cost, not just the write."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_xdatcar_trajectory(workdir / "XDATCAR", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    _cli_ok(
        [
            "convert",
            str(src),
            "--to",
            "extxyz",
            "-o",
            str(workdir / "out.xyz"),
            "--validation-report",
            str(workdir / "validation.json"),
        ]
    )
    return {"frames": float(sz.n_frames), "atoms": float(sz.n_atoms)}


def _bench_parse_vasprun_10k(workdir: Path, scale: str) -> dict[str, float]:
    """Materialize a full 10k-step vasprun.xml — the ``∝ frames`` cost the ≤2 GB bound guards.

    vasprun.xml reaches 10⁴ configurations for MD runs, exactly like XDATCAR; the reader is
    ``iterparse``-streaming but ``parse`` materializes, so this measures the whole-object cost."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_vasprun_trajectory(
        workdir / "vasprun.xml", n_frames=sz.n_frames, n_atoms=sz.n_atoms
    )
    parser = default_registry().get_parser("vasprun")
    with src.open("rb") as fh:
        obj = parser.parse(fh, filename=src.name).canonical
    return {"frames": float(obj.frame_count), "atoms": float(sz.n_atoms)}


def _bench_parse_outcar_10k(workdir: Path, scale: str) -> dict[str, float]:
    """Materialize a full 10k-step OUTCAR — the line-scanned log counterpart of the vasprun row.

    OUTCAR is a log, so its ordinary size at MD scale is also a full trajectory; ``parse``
    materializes the streamed read, so this is the whole-object cost the ≤2 GB bound guards."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_outcar_trajectory(workdir / "OUTCAR", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    parser = default_registry().get_parser("outcar")
    with src.open("rb") as fh:
        obj = parser.parse(fh, filename=src.name).canonical
    return {"frames": float(obj.frame_count), "atoms": float(sz.n_atoms)}


def _bench_convert_outcar_to_extxyz_10k(workdir: Path, scale: str) -> dict[str, float]:
    """The flagship VASP → MLIP conversion at 10⁴ scale, via the real CLI with validation: parse →
    convert → re-parse-and-diff. The ``--validation-report`` flag forces the post-conversion
    re-parse, so this is the end-to-end pipeline cost of producing a label-complete training
    file, not just the write."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_outcar_trajectory(workdir / "OUTCAR", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    _cli_ok(
        [
            "convert",
            str(src),
            "--to",
            "extxyz",
            "-o",
            str(workdir / "out.xyz"),
            "--validation-report",
            str(workdir / "validation.json"),
        ]
    )
    return {"frames": float(sz.n_frames), "atoms": float(sz.n_atoms)}


def _bench_parse_qeout_10k(workdir: Path, scale: str) -> dict[str, float]:
    """Materialize a full 10k-step pw.x output — the QE log's ordinary MD scale (D197).

    A pw.x MD output is a line-scanned log that reaches 10⁴ ionic steps exactly like OUTCAR;
    ``parse`` materializes the streamed read, so this is the whole-object cost the ≤2 GB
    bound guards, measured against the same generator the M52 streaming gate uses."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_qe_pw_out_trajectory(workdir / "pw.out", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    parser = default_registry().get_parser("qe_pw_out")
    with src.open("rb") as fh:
        obj = parser.parse(fh, filename=src.name).canonical
    return {"frames": float(obj.frame_count), "atoms": float(sz.n_atoms)}


def _bench_convert_qeout_to_extxyz_10k(workdir: Path, scale: str) -> dict[str, float]:
    """The QE → MLIP reference-data conversion at 10⁴ scale (D197), via the real CLI with
    validation: parse → convert → re-parse-and-diff. The ``--validation-report`` flag forces
    the post-conversion re-parse, so this is the end-to-end pipeline cost of producing a
    label-complete QE training file (energy/forces/stress per step), not just the write."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_qe_pw_out_trajectory(workdir / "pw.out", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    _cli_ok(
        [
            "convert",
            str(src),
            "--to",
            "extxyz",
            "-o",
            str(workdir / "out.xyz"),
            "--validation-report",
            str(workdir / "validation.json"),
        ]
    )
    return {"frames": float(sz.n_frames), "atoms": float(sz.n_atoms)}


def _bench_parse_lammpsdump_10k(workdir: Path, scale: str) -> dict[str, float]:
    """Materialize a full 10k-frame LAMMPS dump — the ``∝ frames`` cost the ≤2 GB bound guards.

    A dump is the deployment-trajectory format (train → deploy → produce → relabel): production
    dumps reach 10⁴ snapshots exactly like XDATCAR, and the parser is streaming but ``parse``
    materializes, so this measures the whole-object cost the bound guards."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_lammps_dump_trajectory(
        workdir / "dump.lammpstrj", n_frames=sz.n_frames, n_atoms=sz.n_atoms
    )
    parser = default_registry().get_parser("lammps_dump")
    with src.open("rb") as fh:
        obj = parser.parse(fh, filename=src.name).canonical
    return {"frames": float(obj.frame_count), "atoms": float(sz.n_atoms)}


def _bench_convert_lammpsdump_to_extxyz_10k(workdir: Path, scale: str) -> dict[str, float]:
    """The deployment-format → MLIP conversion at 10⁴ scale, via the real CLI with validation:
    parse → convert → re-parse-and-diff. The generated dump declares its units, so no recovery
    preset is needed; the ``--validation-report`` flag forces the post-conversion re-parse, so
    this is the end-to-end pipeline cost of producing a label-complete relabel file, not just
    the write."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_lammps_dump_trajectory(
        workdir / "dump.lammpstrj", n_frames=sz.n_frames, n_atoms=sz.n_atoms
    )
    _cli_ok(
        [
            "convert",
            str(src),
            "--to",
            "extxyz",
            "-o",
            str(workdir / "out.xyz"),
            "--validation-report",
            str(workdir / "validation.json"),
        ]
    )
    return {"frames": float(sz.n_frames), "atoms": float(sz.n_atoms)}


def _bench_convert_extxyz_roundtrip_1k(workdir: Path, scale: str) -> dict[str, float]:
    """1,000 frames × 1,000 atoms, extXYZ → extXYZ identity round-trip with validation — the
    widest single frame in the corpus (the ≤3 GB bound is the per-frame-width headroom)."""
    sz = _sized(scale, full=Scale(1_000, 1_000), micro=Scale(8, 8))
    src = write_extxyz_trajectory(workdir / "traj.xyz", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    _cli_ok(
        [
            "convert",
            str(src),
            "--to",
            "extxyz",
            "-o",
            str(workdir / "out.xyz"),
            "--validation-report",
            str(workdir / "validation.json"),
        ]
    )
    return {"frames": float(sz.n_frames), "atoms": float(sz.n_atoms)}


def _bench_frame_limit_ceiling(workdir: Path, scale: str) -> dict[str, float]:
    """Stream-convert a 100,000-frame file (the ``06 §5`` cap) through the *frame-chunked* path —
    ``parse_stream`` → ``export_stream``, the same helper the M12/M13 memory gate measures. This is
    the one benchmark that must bypass the CLI: ``xtalate convert`` materializes (it slurps the
    whole file), and the spec is explicit that "an implementation that materializes all frames
    simultaneously cannot pass ``frame_limit_ceiling``". Completing (child exit 0) with a peak RSS
    far below the materialized cost is the sub-linear-memory demonstration; the strict
    stream-vs-materialize ratio is asserted in ``tests/streaming/test_streaming_memory.py``, and
    here the ceiling-scale streaming peak is the tracked number the nightly tripwire watches."""
    sz = _sized(scale, full=Scale(100_000, 10), micro=Scale(200, 4))
    src = write_xdatcar_trajectory(workdir / "XDATCAR", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    registry = default_registry()
    parser = registry.get_parser("xdatcar")
    exporter = registry.get_exporter("extxyz")
    with src.open("rb") as fh, (workdir / "out.xyz").open("wb") as out_fh:
        stream = parser.parse_stream(fh, filename=src.name)
        export_stream(exporter, stream.header, stream.frames(), out_fh)
    return {"frames": float(sz.n_frames), "atoms": float(sz.n_atoms)}


def _bench_preflight_latency(workdir: Path, scale: str) -> dict[str, float]:
    """Pre-flight must feel instant in the UI (``07 §2.3``). Parse a 10k-frame object *once* outside
    the timed region — the spec workload is the diff on an "already-parsed object" — then time only
    ``build_preflight``. The ≤1 s budget is measured against ``preflight_seconds``, not the child's
    total wall time (which includes the untimed 10k parse)."""
    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(20, 8))
    src = write_xdatcar_trajectory(workdir / "XDATCAR", n_frames=sz.n_frames, n_atoms=sz.n_atoms)
    registry = default_registry()
    with src.open("rb") as fh:
        obj = registry.get_parser("xdatcar").parse(fh, filename=src.name).canonical
    matrix = registry.capability_matrix()
    start = time.perf_counter()
    build_preflight(obj, matrix, "poscar")
    preflight_seconds = time.perf_counter() - start
    return {"frames": float(obj.frame_count), "preflight_seconds": preflight_seconds}


def _process_rss_bytes(pid: int) -> int:
    """Another process's current RSS in bytes, via ``ps -o rss=`` (KiB on macOS and Linux).

    The server under test runs in a subprocess, so its memory cannot be read with
    ``resource.getrusage(RUSAGE_SELF)`` (that is the *child's own* high-water mark); sampling the
    server's RSS after each ranged read is the honest "server-side memory stays flat" number.
    ``ps`` is available on both supported platforms — no new dependency."""
    out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True)
    return int(out.strip()) * 1024


def _bench_geometry_endpoint_1e4_frames(workdir: Path, scale: str) -> dict[str, float]:
    """The M59-S3 spike: ranged reads of a 10⁴-frame extXYZ through the **S1 end-
    point** on a real uvicorn server, measuring server-side memory across a sliding read window.

    The geometry endpoint streams through the streaming seam (never materializing the whole
    trajectory) and holds a byte-bounded cache of projected objects; the S3 question is whether
    server memory stays **flat** across scrubs. The first ranged read parses the stream once and
    (the 10⁴×8 projection fits the default 16 MB cache bound) caches the full projection; every
    later read slices a window from cache. RSS is sampled after each read; ``server_rss_growth``
    (last − after-first) is the flatness number — a leak or an unbounded accumulation would show
    as a rising line. Scrub latency is per-window wall time (cache-served after the first read).
    Measured-not-gated: the budget is a reported target, never a non-zero exit.
    """
    import httpx  # service/dev dependency, lazily imported like the ase case above
    from alembic import command
    from alembic.config import Config

    sz = _sized(scale, full=Scale(10_000, 8), micro=Scale(200, 4))
    src = write_extxyz_trajectory(workdir / "spike.xyz", n_frames=sz.n_frames, n_atoms=sz.n_atoms)

    # A free loopback port for the server under test.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    db_path = workdir / "spike.db"
    objects_root = workdir / "objects"

    # Migrate the temp SQLite database, then boot the real API against temp DB + object store.
    # (``-x db_url=`` is the literal SQLAlchemy URL, dialect included — same value server reads.)
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.cmd_opts = type("_Opts", (), {"x": [f"db_url=sqlite+pysqlite:///{db_path}"]})()
    command.upgrade(cfg, "head")
    env = dict(os.environ)
    env.update(
        {
            "XTALATE_DATABASE_URL": f"sqlite+pysqlite:///{db_path}",
            "XTALATE_OBJECT_STORE_ROOT": str(objects_root),
        }
    )
    driver = (
        "import uvicorn; "
        "from backend.app import create_app; "
        f"uvicorn.run(create_app(), host='127.0.0.1', port={port}, log_level='warning')"
    )
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen([sys.executable, "-c", driver], env=env, cwd=str(repo_root))
    try:
        deadline = time.monotonic() + 60.0
        while True:
            try:
                with urllib.request.urlopen(f"{base_url}/v1/health?ready=true", timeout=2) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("geometry-endpoint benchmark: server did not become ready")
            time.sleep(0.25)

        with httpx.Client(timeout=120.0) as client:
            with src.open("rb") as fh:
                up = client.post(
                    f"{base_url}/v1/upload",
                    files={"file": (src.name, fh, "chemical/x-xyz")},
                )
            up.raise_for_status()
            file_id = str(up.json()["file_id"])

            # Warm-up reads: one window read to establish the cache, then sample the baseline.
            r = client.get(f"{base_url}/v1/files/{file_id}/geometry", params={"frames": "0:100"})
            r.raise_for_status()
            first_body = r.json()
            rss_after_first = _process_rss_bytes(proc.pid)
            first_read_seconds = float(
                r.elapsed.total_seconds()
            )  # timing below is per-read, not the warm-up

            # The sliding window: ten 100-frame windows spread across the 10⁴-frame trajectory.
            latencies: list[float] = []
            for start in range(0, sz.n_frames, max(sz.n_frames // 10, 1)):
                end = min(start + 100, sz.n_frames)
                t0 = time.perf_counter()
                r = client.get(
                    f"{base_url}/v1/files/{file_id}/geometry",
                    params={"frames": f"{start}:{end}"},
                )
                r.raise_for_status()
                latencies.append(time.perf_counter() - t0)
            rss_after_last = _process_rss_bytes(proc.pid)

        return {
            "frames": float(first_body["frame_count"]),
            "atoms": float(sz.n_atoms),
            "first_read_seconds": first_read_seconds,
            "scrub_median_seconds": float(sorted(latencies)[len(latencies) // 2]),
            "server_rss_after_first_bytes": float(rss_after_first),
            "server_rss_after_last_bytes": float(rss_after_last),
            "server_rss_growth_bytes": float(rss_after_last - rss_after_first),
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _bench_geometry_endpoint_high_atoms(workdir: Path, scale: str) -> dict[str, float]:
    """The M61-S3 honest-degradation latency figure (10⁴ × 100+ atoms): the same geometry
    endpoint on a cache-**exceeding** seed that re-streams + re-parses per range.

    The 10⁴×8 projection fits the endpoint's byte-bounded cache, so a cache-served scrub is ~ms
    (the M59 small-fixture number); a 10⁴×100 seed exceeds that bound, so each ranged read
    re-streams the whole file and re-parses — about a second per window (D232's byte-bounded
    cache). ``scrub_median_seconds`` / ``scrub_max_seconds`` are that honest per-window latency:
    what the browser-facing scrubber degrades to at high atom counts, the number S3 surfaces (a
    warm/larger client window + prefetch of the next window + the explicit slower-scrub
    affordance) rather than hiding behind the cache-served small-fixture figure. Boots its own
    server at the default upload ceiling (not the 1 MiB e2e shared ceiling), so it is not
    ceiling-bound. Measured-not-gated: a reported number for M63's comparison baseline, never a
    non-zero exit.
    """
    import urllib.request

    import httpx  # service/dev dependency, lazily imported like the ase case above

    sz = _sized(scale, full=Scale(10_000, 100), micro=Scale(200, 8))
    src = write_extxyz_trajectory(workdir / "wide.xyz", n_frames=sz.n_frames, n_atoms=sz.n_atoms)

    # A free loopback port for the server under test.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    db_path = workdir / "spike.db"
    objects_root = workdir / "objects"

    # Migrate the temp SQLite database, then boot the real API against temp DB + object store.
    # (``-x db_url=`` is the literal SQLAlchemy URL, dialect included — same value server reads.)
    from alembic import command
    from alembic.config import Config

    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.cmd_opts = type("_Opts", (), {"x": [f"db_url=sqlite+pysqlite:///{db_path}"]})()
    command.upgrade(cfg, "head")
    env = dict(os.environ)
    env.update(
        {
            "XTALATE_DATABASE_URL": f"sqlite+pysqlite:///{db_path}",
            "XTALATE_OBJECT_STORE_ROOT": str(objects_root),
        }
    )
    driver = (
        "import uvicorn; "
        "from backend.app import create_app; "
        f"uvicorn.run(create_app(), host='127.0.0.1', port={port}, log_level='warning')"
    )
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen([sys.executable, "-c", driver], env=env, cwd=str(repo_root))
    try:
        deadline = time.monotonic() + 60.0
        while True:
            try:
                with urllib.request.urlopen(f"{base_url}/v1/health?ready=true", timeout=2) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("geometry-endpoint benchmark: server did not become ready")
            time.sleep(0.25)

        with httpx.Client(timeout=300.0) as client:
            with src.open("rb") as fh:
                up = client.post(
                    f"{base_url}/v1/upload",
                    files={"file": (src.name, fh, "chemical/x-xyz")},
                )
            up.raise_for_status()
            file_id = str(up.json()["file_id"])

            # Warm-up read to establish (or miss) the projection cache, then the baseline RSS.
            r = client.get(f"{base_url}/v1/files/{file_id}/geometry", params={"frames": "0:100"})
            r.raise_for_status()
            first_body = r.json()
            rss_after_first = _process_rss_bytes(proc.pid)
            first_read_seconds = float(r.elapsed.total_seconds())

            # The sliding window: ten 100-frame windows spread across the 10⁴-frame trajectory;
            # each is a re-stream on a cache-exceeding seed — the latency the scrubber feels.
            latencies: list[float] = []
            for start in range(0, sz.n_frames, max(sz.n_frames // 10, 1)):
                end = min(start + 100, sz.n_frames)
                t0 = time.perf_counter()
                r = client.get(
                    f"{base_url}/v1/files/{file_id}/geometry",
                    params={"frames": f"{start}:{end}"},
                )
                r.raise_for_status()
                latencies.append(time.perf_counter() - t0)
            rss_after_last = _process_rss_bytes(proc.pid)

        ordered = sorted(latencies)
        return {
            "frames": float(first_body["frame_count"]),
            "atoms": float(sz.n_atoms),
            "first_read_seconds": first_read_seconds,
            "scrub_median_seconds": float(ordered[len(ordered) // 2]),
            "scrub_max_seconds": float(ordered[-1]),
            "server_rss_growth_bytes": float(rss_after_last - rss_after_first),
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _bench_batch_convert_100_files(workdir: Path, scale: str) -> dict[str, float]:
    """The v1.5 batch fan-out (M54/M58) at the 100-file scale: N ordinary files → one aggregate.

    Each source converts through the **ordinary single-file path** (parse → convert → validate)
    and the aggregate embeds the per-file reports — the aggregate **holds reports, never
    frames**, which is the memory-boundary this benchmark measures: ``aggregate_bytes`` is the
    serialized ``BatchReport`` (report-scale: ~a few KB per file), and its budget would flag a
    regression that ever held the converted frames (25,000 frames ≈ 10² MB) instead. The batch
    re-implements none of the convert path; the streaming engines run per child exactly as a
    lone ``xtalate convert`` does."""
    sz = _sized(scale, full=Scale(100, 50), micro=Scale(4, 8))
    n_files, n_atoms = sz.n_frames, sz.n_atoms  # n_frames doubles as the file count here
    frames_per_file = 5
    sources = [
        write_lammps_dump_trajectory(
            workdir / f"job_{i:03d}.dump", n_frames=frames_per_file, n_atoms=n_atoms
        )
        for i in range(n_files)
    ]
    manifest = BatchManifest(
        sources=[str(src) for src in sources], target="extxyz", output_mode="per-file"
    )
    report = run_batch(manifest, default_registry())
    aggregate_bytes = float(len(report.model_dump_json().encode("utf-8")))
    return {
        "files": float(n_files),
        "frames_total": float(n_files * frames_per_file),
        "aggregate_bytes": aggregate_bytes,
    }


def _bench_parse_asedb_1k_rows(workdir: Path, scale: str) -> dict[str, float]:
    """Parse an ASE SQLite ``.db`` at 1,000-row scale (M55-S1): the whole-file read via
    ``ase.db`` ``select()`` — a multi-row database's honest terminal outcome is the recoverable
    ``ASEDB_MULTIPLE_ROWS`` refusal (a dataset is aggregation, never one Canonical Object), and
    the read that reaches it is exactly what this measures. Generated, never committed: the
    database is written here with ``ase.db`` itself, the same library the parser reads."""
    sz = _sized(scale, full=Scale(1_000, 8), micro=Scale(20, 4))
    n_rows, n_atoms = sz.n_frames, sz.n_atoms  # n_frames doubles as the row count here
    from ase import Atoms
    from ase.db import connect

    db_path = workdir / "rows.db"
    db = connect(str(db_path), use_lock_file=False)
    for _ in range(n_rows):
        db.write(Atoms("H" * n_atoms, positions=[[float(i), 0.0, 0.0] for i in range(n_atoms)]))
    parser = default_registry().get_parser("ase_db")
    from xtalate.sdk.results import ParseError

    with db_path.open("rb") as fh:
        try:
            parser.parse(fh, filename=db_path.name)
        except ParseError as exc:  # the multi-row terminal outcome, by design
            if not any(issue.code == "ASEDB_MULTIPLE_ROWS" for issue in exc.issues):
                raise
        else:
            raise AssertionError("a 1k-row .db parsed as a single object — the refusal is missing")
    return {"rows": float(n_rows), "atoms": float(n_atoms)}


BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark(
        "parse_xdatcar_10k",
        _bench_parse_xdatcar_10k,
        (Budget("wall_seconds", 30.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "convert_xdatcar_to_extxyz_10k",
        _bench_convert_xdatcar_to_extxyz_10k,
        (Budget("wall_seconds", 90.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "parse_vasprun_10k",
        _bench_parse_vasprun_10k,
        (Budget("wall_seconds", 30.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "parse_outcar_10k",
        _bench_parse_outcar_10k,
        (Budget("wall_seconds", 30.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "convert_outcar_to_extxyz_10k",
        _bench_convert_outcar_to_extxyz_10k,
        (Budget("wall_seconds", 90.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "parse_qeout_10k",
        _bench_parse_qeout_10k,
        (Budget("wall_seconds", 30.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "convert_qeout_to_extxyz_10k",
        _bench_convert_qeout_to_extxyz_10k,
        (Budget("wall_seconds", 90.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "parse_lammpsdump_10k",
        _bench_parse_lammpsdump_10k,
        (Budget("wall_seconds", 30.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "convert_lammpsdump_to_extxyz_10k",
        _bench_convert_lammpsdump_to_extxyz_10k,
        (Budget("wall_seconds", 90.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
    Benchmark(
        "convert_extxyz_roundtrip_1k",
        _bench_convert_extxyz_roundtrip_1k,
        (Budget("wall_seconds", 60.0, "s"), Budget("peak_rss_bytes", 3 * _GiB, "bytes")),
    ),
    # "completes" is the whole bound — child exit 0 is the pass — so no threshold budget. Peak RSS
    # is recorded as a measured-only number (the sub-linear-memory demonstration).
    Benchmark("frame_limit_ceiling", _bench_frame_limit_ceiling, ()),
    # The M59-S3 spike: the S1 geometry endpoint at 10⁴-frame scale. server_rss_growth is the
    # flat-memory number (last − after-first ranged read); measured-not-gated like every budget.
    Benchmark(
        "geometry_endpoint_1e4_frames",
        _bench_geometry_endpoint_1e4_frames,
        (Budget("server_rss_growth_bytes", 64 * 1024 * 1024, "bytes"),),
    ),
    # The M61-S3 honest-degradation latency case: the same endpoint on a 10⁴×100 seed (cache-
    # exceeding) — scrub_median/scrub_max_seconds are the real per-window re-stream latency the
    # browser scrubber degrades to, not the small-fixture cache-served figure. Measured-not-gated.
    Benchmark(
        "geometry_endpoint_high_atoms",
        _bench_geometry_endpoint_high_atoms,
        (Budget("scrub_median_seconds", 10.0, "s"),),
    ),
    Benchmark(
        "preflight_latency",
        _bench_preflight_latency,
        (Budget("preflight_seconds", 1.0, "s"),),
    ),
    # The v1.5 batch fan-out: 100 files through run_batch. aggregate_bytes is the reports-only
    # footprint — the per-file memory boundary (a frame-holding aggregate would blow it by ~2
    # orders of magnitude). Wall budget consistent with the convert_*_10k rows.
    Benchmark(
        "batch_convert_100_files",
        _bench_batch_convert_100_files,
        (
            Budget("wall_seconds", 90.0, "s"),
            Budget("peak_rss_bytes", 2 * _GiB, "bytes"),
            Budget("aggregate_bytes", 64 * 1024 * 1024, "bytes"),
        ),
    ),
    # The M55 ASE-db parser at 1,000-row scale — same budgets as the other parse_*_10k rows.
    Benchmark(
        "parse_asedb_1k_rows",
        _bench_parse_asedb_1k_rows,
        (Budget("wall_seconds", 30.0, "s"), Budget("peak_rss_bytes", 2 * _GiB, "bytes")),
    ),
)

_BY_NAME = {b.name: b for b in BENCHMARKS}


def _peak_rss_bytes(ru_maxrss: int) -> int:
    """Normalize ``ru_maxrss`` to bytes: macOS reports bytes, Linux KiB (see ``getrusage(2)``)."""
    return ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024


def _run_child(name: str, scale: str, result_path: Path) -> None:
    """Run one benchmark in *this* process, measuring its own wall time and peak RSS, and write the
    result JSON to ``result_path``. Invoked as ``python -m benchmarks _child <name> <scale> <path>``
    so every benchmark gets a fresh interpreter (honest per-benchmark peak RSS)."""
    bench = _BY_NAME[name]
    workdir = Path(tempfile.mkdtemp(prefix=f"xtalate-bench-{name}-"))
    gc.collect()
    try:
        start = time.perf_counter()
        metrics = bench.run(workdir, scale)
        wall = time.perf_counter() - start
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    peak = _peak_rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    result: dict[str, Any] = {
        "name": name,
        "scale": scale,
        "wall_seconds": wall,
        "peak_rss_bytes": peak,
        "metrics": metrics,
    }
    result_path.write_text(json.dumps(result), encoding="utf-8")


def _evaluate_budgets(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare each of the benchmark's budgets against the measured value. ``within_budget`` is
    ``None`` when the metric was not reported — measured-only, never a gate."""
    values: dict[str, float] = {
        "wall_seconds": result["wall_seconds"],
        "peak_rss_bytes": result["peak_rss_bytes"],
        **result["metrics"],
    }
    checks: list[dict[str, Any]] = []
    for budget in _BY_NAME[result["name"]].budgets:
        value = values.get(budget.metric)
        checks.append(
            {
                "metric": budget.metric,
                "limit": budget.limit,
                "unit": budget.unit,
                "value": value,
                "within_budget": None if value is None else value <= budget.limit,
            }
        )
    return checks


def _run_all(names: list[str], scale: str) -> list[dict[str, Any]]:
    """Run each named benchmark in its own subprocess, collecting one result record per benchmark.
    A crashed benchmark becomes an ``error`` record (and later a non-zero harness exit)."""
    results: list[dict[str, Any]] = []
    for name in names:
        holder = Path(tempfile.mkdtemp(prefix="xtalate-bench-result-"))
        result_path = holder / "result.json"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "benchmarks", "_child", name, scale, str(result_path)],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0 or not result_path.exists():
                results.append(
                    {
                        "name": name,
                        "scale": scale,
                        "error": f"exit {proc.returncode}",
                        "stderr": proc.stderr[-2000:],
                    }
                )
                continue
            record = json.loads(result_path.read_text(encoding="utf-8"))
            record["budgets"] = _evaluate_budgets(record)
            results.append(record)
        finally:
            shutil.rmtree(holder, ignore_errors=True)
    return results


def _fmt_bytes(n: float) -> str:
    return f"{n / _GiB:.3f} GiB"


def _print_table(results: list[dict[str, Any]]) -> None:
    """A human-readable summary to stdout: one row per benchmark, budget breaches flagged."""
    print(f"{'benchmark':<32} {'scale':<6} {'wall (s)':>10} {'peak RSS':>12}  budgets")
    print("-" * 82)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<32} {r['scale']:<6} {'ERROR':>10} {'':>12}  {r['error']}")
            continue
        flags = []
        for check in r["budgets"]:
            if check["within_budget"] is None:
                continue
            mark = "ok" if check["within_budget"] else "OVER"
            flags.append(f"{check['metric']}={mark}")
        summary = ", ".join(flags) if flags else "measured-only"
        print(
            f"{r['name']:<32} {r['scale']:<6} {r['wall_seconds']:>10.3f} "
            f"{_fmt_bytes(r['peak_rss_bytes']):>12}  {summary}"
        )


def _write_series(results: list[dict[str, Any]], out_dir: Path) -> None:
    """Persist the wall-time + peak-RSS series as JSON and CSV — the artifacts the nightly workflow
    (M15C) uploads and charts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with (out_dir / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv_writer(fh)
        writer.writerow(
            ["name", "scale", "wall_seconds", "peak_rss_bytes", "peak_rss_gib", "budgets_ok"]
        )
        for r in results:
            if "error" in r:
                writer.writerow([r["name"], r["scale"], "", "", "", "ERROR"])
                continue
            evaluated = [c["within_budget"] for c in r["budgets"] if c["within_budget"] is not None]
            budgets_ok = "" if not evaluated else str(all(evaluated))
            writer.writerow(
                [
                    r["name"],
                    r["scale"],
                    f"{r['wall_seconds']:.6f}",
                    r["peak_rss_bytes"],
                    f"{r['peak_rss_bytes'] / _GiB:.6f}",
                    budgets_ok,
                ]
            )


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m benchmarks`` entry point. Returns non-zero only if a benchmark *crashed* — a
    budget breach is reported, never a failure (measured, not gated)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "_child":
        # Internal single-benchmark worker: `_child <name> <scale> <result_path>`.
        _, name, scale, result_path = args
        _run_child(name, scale, Path(result_path))
        return 0

    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Xtalate performance corpus (MASTER_SPEC Part 8 §4) — measured, not gated.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run every benchmark at micro scale (a fast wiring check, not a real measurement).",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="NAME",
        help="Run only this benchmark (repeatable). Default: all ten.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        help="Write results.json and results.csv here (default: print a table to stdout only).",
    )
    parser.add_argument(
        "--tripwire",
        action="store_true",
        help=(
            "After running, compare this run against the trailing-median series for --runner and "
            "EXIT NON-ZERO on a >20%% regression (the nightly gate; pinned runner only). "
            "Requires --runner. See docs/ops/pinned-runner.md."
        ),
    )
    parser.add_argument(
        "--runner",
        metavar="ID",
        default=os.environ.get("XTALATE_BENCH_RUNNER"),
        help=(
            "Pinned-runner identity keying the history series (history/<runner>.jsonl). "
            "Defaults to $XTALATE_BENCH_RUNNER. Required with --tripwire so shared/laptop noise "
            "never enters a pinned series."
        ),
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "history",
        metavar="DIR",
        help="Where the per-runner rolling series live (default: benchmarks/history/).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=tripwire.DEFAULT_THRESHOLD,
        metavar="FRAC",
        help="Regression threshold as a fraction over the median (default: 0.20 = 20%%).",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=tripwire.DEFAULT_WINDOW_DAYS,
        metavar="N",
        help="Trailing window the median is taken over (default: 14 days).",
    )
    ns = parser.parse_args(args)

    if ns.tripwire and not ns.runner:
        parser.error("--tripwire requires --runner (or $XTALATE_BENCH_RUNNER)")
    if ns.tripwire and ns.smoke:
        parser.error("--tripwire compares real measurements; refusing to run against --smoke scale")

    names = ns.only or [b.name for b in BENCHMARKS]
    unknown = [n for n in names if n not in _BY_NAME]
    if unknown:
        parser.error(f"unknown benchmark(s): {', '.join(unknown)}")

    scale = MICRO if ns.smoke else FULL
    results = _run_all(names, scale)

    _print_table(results)
    if ns.out is not None:
        _write_series(results, ns.out)
        print(f"\nwrote {ns.out / 'results.json'} and {ns.out / 'results.csv'}")

    crashed = any("error" in r for r in results)
    if not ns.tripwire:
        return 1 if crashed else 0
    return _run_tripwire(results, ns, crashed=crashed)


def _run_tripwire(results: list[dict[str, Any]], ns: argparse.Namespace, *, crashed: bool) -> int:
    """Compare this run against its runner's trailing-median series, print the verdict, and — only
    for a clean run — append it to the series. Returns non-zero on a crash or a regression."""
    now = datetime.now(tz=UTC)
    current = tripwire.flatten_run(results)
    path = ns.history_dir / f"{ns.runner}.jsonl"
    history = tripwire.load_series(path)
    report = tripwire.evaluate(
        current,
        history,
        now=now,
        threshold=ns.threshold,
        window_days=ns.window_days,
    )
    print()
    print(tripwire.format_report(report))

    if crashed:
        # A crashed benchmark is not a comparable data point — never seed the series with a partial
        # run, and fail regardless of the (partial) tripwire verdict.
        print("\nnot appending to series: a benchmark crashed this run.")
        return 1
    record = tripwire.run_record(
        current, runner=ns.runner, now=now, commit=os.environ.get("GITHUB_SHA")
    )
    tripwire.append_run(path, record, now=now)
    print(f"\nappended this run to {path}")
    return 1 if not report.passed else 0
