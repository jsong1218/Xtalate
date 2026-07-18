"""Xtalate performance corpus + benchmark harness (M15A; MASTER_SPEC Part 8 §4).

Measured, not gated: ``python -m benchmarks`` reproduces the spec's five synthetic benchmarks and
reports wall-time + peak-RSS series against their budgets, but never fails a build on a budget
breach — the regression tripwire lives in the nightly workflow on a pinned runner (M15C). See
``benchmarks/harness.py`` for the full rationale. This tree is deliberately outside the
coverage-gated pytest run (``testpaths = ["tests"]``).
"""

from benchmarks.harness import BENCHMARKS, Benchmark, main

__all__ = ["BENCHMARKS", "Benchmark", "main"]
