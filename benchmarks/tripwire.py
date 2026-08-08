"""The >20% performance-regression tripwire (M37 S2; MASTER_SPEC Part 8 §4 / §6 item 5).

The benchmark harness is *measured, not gated*: it reports wall-time and peak-RSS against the spec
budgets but never fails a build on a budget breach, because shared CI runners are too noisy for an
absolute time bound to hold week to week (``harness.py`` docstring). This module is the *relative*
gate the harness deliberately omits — the "regression tripwire against a rolling median" the nightly
comment long promised ("read the trend by hand until the tripwire lands"). It answers a
different, noise-robust question:

    Did *this* run regress a tracked metric by more than 20% against the **median of the trailing
    14 days on the same runner**?

Two properties make that trustworthy where an absolute budget is not:

* **Median, not last value.** A single slow run cannot trip it, and cannot poison the baseline for
  the next run — the median of ~14 samples shrugs off one outlier in either direction.
* **Per-runner series.** The comparison is only ever within one runner's own history
  (``history/<runner>.jsonl``), so this must run on a **pinned** runner (a registered self-hosted
  runner on fixed silicon); laptop or shared ``ubuntu-latest`` noise must never enter the series.
  Gating lives in the caller (``harness --tripwire`` requires a ``--runner`` id; the nightly job
  running it is guarded to the pinned runner). See ``docs/ops/pinned-runner.md``.

This module is **pure standard library** and knows nothing about how a benchmark runs — it operates
on the harness's result dicts and on a JSONL series file. That keeps its unit test
(``tests/benchmarks/test_tripwire.py``) fast and independent of a real (minutes-long) benchmark run.

**A tripwire trip is a real failure** (the caller exits non-zero, the nightly job goes red and opens
the tracking issue). The fix is to investigate the regression, never to widen the threshold or prune
the series to make it green — that would invert the gate exactly as lowering the coverage floor
would.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

# The regression threshold and window are the two knobs; both are Part 8 §4's numbers. A metric is
# "regressed" when the current value exceeds the trailing median by more than THRESHOLD (all tracked
# metrics are wall-time or memory — lower is always better, so a regression is always an increase).
DEFAULT_THRESHOLD = 0.20  # >20% worse than the median (Part 8 §4 / §6 item 5).
DEFAULT_WINDOW_DAYS = 14  # the trailing window the median is taken over.
# How much history to keep on disk. The window reader only ever looks back DEFAULT_WINDOW_DAYS, but
# retaining a bit more than that leaves headroom to widen the window without losing data, while
# bounding the committed file's growth.
DEFAULT_RETAIN_DAYS = 60

# The two metrics every completed benchmark reports; watched for every benchmark, budget or not
# (this is what lets the tripwire watch `frame_limit_ceiling`'s streaming peak RSS, which has no
# absolute budget — harness.py docstring). Any additional budgeted metric (e.g. `preflight_seconds`)
# is read from the result's own `budgets` list, so this module never imports the benchmark table.
_UNIVERSAL_METRICS = ("wall_seconds", "peak_rss_bytes")


def flatten_run(results: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Flatten a harness run (a list of per-benchmark result dicts) into ``{"<bench>.<metric>":
    value}``, the shape stored in the series and compared by :func:`evaluate`.

    Watched per benchmark: ``wall_seconds`` and ``peak_rss_bytes`` (always present) plus any metric
    named in that benchmark's ``budgets`` (e.g. ``preflight_seconds``). Benchmarks that *crashed*
    (an ``error`` record) contribute nothing — a run with any crash is not a comparable data point,
    and the caller does not append it to the series.
    """
    flat: dict[str, float] = {}
    for result in results:
        if "error" in result:
            continue
        name = result["name"]
        values: dict[str, Any] = {
            "wall_seconds": result.get("wall_seconds"),
            "peak_rss_bytes": result.get("peak_rss_bytes"),
            **result.get("metrics", {}),
        }
        wanted = set(_UNIVERSAL_METRICS)
        wanted.update(check["metric"] for check in result.get("budgets", []))
        for metric in wanted:
            value = values.get(metric)
            if value is not None:
                flat[f"{name}.{metric}"] = float(value)
    return flat


@dataclass(frozen=True)
class MetricComparison:
    """One metric's tripwire verdict: the current value against its trailing median."""

    metric: str
    current: float
    median: float | None  # None when there is no prior data in the window (a baseline sample).
    allowed: float | None  # median * (1 + threshold); None at baseline.
    samples: int  # how many prior in-window values the median was taken over.
    regressed: bool

    @property
    def ratio(self) -> float | None:
        """Current / median — how much worse (``> 1``) or better (``< 1``) than the baseline."""
        if self.median is None or self.median == 0:
            return None
        return self.current / self.median


@dataclass(frozen=True)
class TripwireReport:
    """The whole-run verdict: one :class:`MetricComparison` per watched metric, and a pass flag."""

    comparisons: tuple[MetricComparison, ...]
    threshold: float
    window_days: int

    @property
    def regressions(self) -> tuple[MetricComparison, ...]:
        return tuple(c for c in self.comparisons if c.regressed)

    @property
    def passed(self) -> bool:
        return not self.regressions

    @property
    def had_baseline(self) -> bool:
        """True once at least one metric had prior in-window data to compare against."""
        return any(c.median is not None for c in self.comparisons)


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp from the series, normalizing to an aware UTC datetime."""
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def window_values(
    history: Iterable[Mapping[str, Any]],
    metric: str,
    *,
    now: datetime,
    window_days: int,
) -> list[float]:
    """The prior values of ``metric`` from runs within the trailing ``window_days`` of ``now``.

    A run contributes only if it carries the metric; runs outside the window or missing the metric
    (e.g. before it was tracked) are simply absent — the median is taken over whatever remains.
    """
    cutoff = now - timedelta(days=window_days)
    out: list[float] = []
    for record in history:
        ts = record.get("timestamp")
        metrics = record.get("metrics", {})
        if ts is None or metric not in metrics:
            continue
        if _parse_ts(ts) >= cutoff:
            out.append(float(metrics[metric]))
    return out


def evaluate(
    current: Mapping[str, float],
    history: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    threshold: float = DEFAULT_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> TripwireReport:
    """Compare ``current`` (a flat metric map from :func:`flatten_run`) against the trailing-median
    of ``history``. A metric with no in-window prior data is a *baseline* sample: it cannot regress
    (there is nothing to regress against) and passes, seeding the series for next time.
    """
    comparisons: list[MetricComparison] = []
    for metric in sorted(current):
        value = current[metric]
        prior = window_values(history, metric, now=now, window_days=window_days)
        if not prior:
            comparisons.append(MetricComparison(metric, value, None, None, 0, regressed=False))
            continue
        med = float(median(prior))
        allowed = med * (1 + threshold)
        comparisons.append(
            MetricComparison(
                metric,
                value,
                med,
                allowed,
                len(prior),
                regressed=value > allowed,
            )
        )
    return TripwireReport(tuple(comparisons), threshold, window_days)


def run_record(
    current: Mapping[str, float],
    *,
    runner: str,
    now: datetime,
    commit: str | None = None,
) -> dict[str, Any]:
    """Build the one JSONL record a passing/seeding run appends to its runner's series."""
    record: dict[str, Any] = {
        "timestamp": now.astimezone(UTC).isoformat(),
        "runner": runner,
        "metrics": dict(current),
    }
    if commit is not None:
        record["commit"] = commit
    return record


def load_series(path: Path) -> list[dict[str, Any]]:
    """Read a runner's JSONL series (one run per line). A missing file is an empty series (the
    cold-start case). Blank lines are ignored; a malformed line is a corrupt series and raises."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def append_run(
    path: Path,
    record: Mapping[str, Any],
    *,
    now: datetime,
    retain_days: int = DEFAULT_RETAIN_DAYS,
) -> None:
    """Append ``record`` to the series at ``path`` and prune entries older than ``retain_days`` so
    the committed file stays bounded. Rewrites the file (append + prune in one pass); creates the
    parent directory if needed."""
    existing = load_series(path)
    cutoff = now - timedelta(days=retain_days)
    kept = [
        r
        for r in existing
        if r.get("timestamp") is not None and _parse_ts(r["timestamp"]) >= cutoff
    ]
    kept.append(dict(record))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in kept),
        encoding="utf-8",
    )


def format_report(report: TripwireReport) -> str:
    """A human-readable summary for the CI log: one line per metric, regressions flagged."""
    lines = [
        f"regression tripwire — >{report.threshold:.0%} over {report.window_days}-day median",
        f"{'metric':<44} {'current':>12} {'median':>12} {'ratio':>7}  status",
        "-" * 88,
    ]
    for c in sorted(report.comparisons, key=lambda x: x.metric):
        if c.median is None:
            status, med, ratio = "baseline", "—", "—"
        elif c.regressed:
            status = "REGRESSED"
            med = f"{c.median:.4g}"
            ratio = f"{c.ratio:.2f}x" if c.ratio is not None else "—"
        else:
            status = "ok"
            med = f"{c.median:.4g}"
            ratio = f"{c.ratio:.2f}x" if c.ratio is not None else "—"
        lines.append(f"{c.metric:<44} {c.current:>12.4g} {med:>12} {ratio:>7}  {status}")
    verdict = "PASS" if report.passed else f"FAIL — {len(report.regressions)} metric(s) regressed"
    lines.append("-" * 88)
    lines.append(verdict)
    return "\n".join(lines)
