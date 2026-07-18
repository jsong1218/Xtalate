"""The M15A synthetic performance corpus + benchmark harness (measured, not gated).

Turns the "large trajectory performance" risk (MASTER_SPEC Part 8 §4) into a tracked number
rather than an anecdote. Five benchmarks reproduce the spec's performance table exactly:

* ``parse_xdatcar_10k`` — parse XDATCAR, 10,000 frames × 100 atoms — ≤ 30 s, peak RSS ≤ 2 GB.
* ``convert_xdatcar_to_extxyz_10k`` — full pipeline incl. validation, same file — ≤ 90 s, ≤ 2 GB.
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
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from csv import writer as csv_writer
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.streaming._generators import (
    write_extxyz_trajectory,
    write_xdatcar_trajectory,
)

from xtalate.cli.main import EXIT_OK
from xtalate.cli.main import main as cli_main
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
        "convert_extxyz_roundtrip_1k",
        _bench_convert_extxyz_roundtrip_1k,
        (Budget("wall_seconds", 60.0, "s"), Budget("peak_rss_bytes", 3 * _GiB, "bytes")),
    ),
    # "completes" is the whole bound — child exit 0 is the pass — so no threshold budget. Peak RSS
    # is recorded as a measured-only number (the sub-linear-memory demonstration).
    Benchmark("frame_limit_ceiling", _bench_frame_limit_ceiling, ()),
    Benchmark(
        "preflight_latency",
        _bench_preflight_latency,
        (Budget("preflight_seconds", 1.0, "s"),),
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
        help="Run only this benchmark (repeatable). Default: all five.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        help="Write results.json and results.csv here (default: print a table to stdout only).",
    )
    ns = parser.parse_args(args)

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

    return 1 if any("error" in r for r in results) else 0
