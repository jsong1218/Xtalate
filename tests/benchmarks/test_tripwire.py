"""Unit tests for the >20% performance-regression tripwire (M37 S2; benchmarks/tripwire.py).

These are the tripwire's own gate: a synthetic **>20% regression trips it**, a within-noise series
**passes**, a cold start **seeds without tripping**, and the median **shrugs off a single outlier**.
The comparator is pure and fast — it never runs a real (minutes-long) benchmark — so these can live
in the ordinary pytest suite alongside the code they guard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from benchmarks import tripwire

NOW = datetime(2026, 8, 6, 7, 0, 0, tzinfo=UTC)


def _result(
    name: str, wall: float, rss: float, extra_budgets: dict[str, float] | None = None
) -> dict[str, Any]:
    """A harness-shaped per-benchmark result dict. ``extra_budgets`` adds budgeted metrics beyond
    the universal wall/RSS pair (e.g. ``preflight_seconds``)."""
    budgets = [{"metric": "wall_seconds"}, {"metric": "peak_rss_bytes"}]
    metrics: dict[str, float] = {"frames": 10_000.0}
    for metric, value in (extra_budgets or {}).items():
        budgets.append({"metric": metric})
        metrics[metric] = value
    return {
        "name": name,
        "wall_seconds": wall,
        "peak_rss_bytes": rss,
        "metrics": metrics,
        "budgets": budgets,
    }


def _record(ts: datetime, metrics: dict[str, float]) -> dict[str, object]:
    return {"timestamp": ts.isoformat(), "runner": "pinned", "metrics": metrics}


# --- flatten_run ---------------------------------------------------------------------------------


def test_flatten_watches_universal_and_budgeted_metrics_only() -> None:
    flat = tripwire.flatten_run(
        [
            _result("parse_xdatcar_10k", 12.0, 100.0),
            _result("preflight_latency", 3.0, 50.0, extra_budgets={"preflight_seconds": 0.4}),
        ]
    )
    assert flat == {
        "parse_xdatcar_10k.wall_seconds": 12.0,
        "parse_xdatcar_10k.peak_rss_bytes": 100.0,
        "preflight_latency.wall_seconds": 3.0,
        "preflight_latency.peak_rss_bytes": 50.0,
        "preflight_latency.preflight_seconds": 0.4,
    }
    # A non-budgeted informational metric (frames) is not watched.
    assert "parse_xdatcar_10k.frames" not in flat


def test_flatten_skips_crashed_benchmarks() -> None:
    flat = tripwire.flatten_run(
        [
            _result("parse_xdatcar_10k", 12.0, 100.0),
            {"name": "frame_limit_ceiling", "error": "exit 1", "scale": "full"},
        ]
    )
    assert set(flat) == {"parse_xdatcar_10k.wall_seconds", "parse_xdatcar_10k.peak_rss_bytes"}


# --- evaluate ------------------------------------------------------------------------------------


def test_cold_start_is_a_baseline_that_passes() -> None:
    report = tripwire.evaluate({"a.wall_seconds": 10.0}, [], now=NOW)
    assert report.passed
    assert not report.had_baseline
    (only,) = report.comparisons
    assert only.median is None and only.samples == 0 and not only.regressed


def test_within_noise_series_passes() -> None:
    history = [
        _record(NOW - timedelta(days=d), {"a.wall_seconds": 10.0 + (d % 2)}) for d in range(1, 8)
    ]
    report = tripwire.evaluate({"a.wall_seconds": 11.0}, history, now=NOW)
    assert report.passed and report.had_baseline


def test_regression_over_twenty_percent_trips() -> None:
    history = [_record(NOW - timedelta(days=d), {"a.wall_seconds": 10.0}) for d in range(1, 8)]
    # median is 10.0; 20% allowance is 12.0; 12.5 is a regression.
    report = tripwire.evaluate({"a.wall_seconds": 12.5}, history, now=NOW)
    assert not report.passed
    (comp,) = report.comparisons
    assert comp.regressed and comp.median == 10.0 and comp.allowed == 12.0
    assert comp.ratio == 1.25
    assert "REGRESSED" in tripwire.format_report(report)


def test_exactly_at_threshold_does_not_trip() -> None:
    history = [_record(NOW - timedelta(days=d), {"a.wall_seconds": 10.0}) for d in range(1, 8)]
    # Exactly +20% (== allowed) is not a regression — the gate is strictly greater-than.
    report = tripwire.evaluate({"a.wall_seconds": 12.0}, history, now=NOW)
    assert report.passed
    assert "PASS" in tripwire.format_report(report)


def test_median_ignores_a_single_outlier_in_the_window() -> None:
    # Six runs at 10s and one freak 100s run. The median is still 10s, so a 12.5s run trips (it is a
    # real regression against the typical value), and a normal 11s run does not.
    history = [_record(NOW - timedelta(days=d), {"a.wall_seconds": 10.0}) for d in range(1, 7)]
    history.append(_record(NOW - timedelta(days=7), {"a.wall_seconds": 100.0}))
    assert tripwire.evaluate({"a.wall_seconds": 11.0}, history, now=NOW).passed
    assert not tripwire.evaluate({"a.wall_seconds": 12.5}, history, now=NOW).passed


def test_out_of_window_history_is_ignored() -> None:
    # A fast historical baseline that has aged out of the window must not gate a slower run.
    history = [_record(NOW - timedelta(days=30), {"a.wall_seconds": 5.0})]
    report = tripwire.evaluate({"a.wall_seconds": 20.0}, history, now=NOW, window_days=14)
    assert report.passed  # nothing in-window → baseline, not a regression against the stale 5.0
    (comp,) = report.comparisons
    assert comp.median is None


def test_a_new_metric_against_old_history_is_a_baseline() -> None:
    history = [_record(NOW - timedelta(days=d), {"a.wall_seconds": 10.0}) for d in range(1, 5)]
    report = tripwire.evaluate({"b.wall_seconds": 99.0}, history, now=NOW)
    assert report.passed  # metric "b" has no prior data → seeds, never trips.


# --- series I/O ----------------------------------------------------------------------------------


def test_load_missing_series_is_empty(tmp_path: Path) -> None:
    assert tripwire.load_series(tmp_path / "pinned.jsonl") == []


def test_append_round_trips_and_prunes_old_entries(tmp_path: Path) -> None:
    path = tmp_path / "pinned.jsonl"
    stale = _record(NOW - timedelta(days=90), {"a.wall_seconds": 10.0})
    recent = _record(NOW - timedelta(days=3), {"a.wall_seconds": 10.0})
    tripwire.append_run(path, stale, now=NOW)
    tripwire.append_run(path, recent, now=NOW)

    new = tripwire.run_record({"a.wall_seconds": 11.0}, runner="pinned", now=NOW, commit="abc1234")
    tripwire.append_run(path, new, now=NOW, retain_days=60)

    series = tripwire.load_series(path)
    # The 90-day-old entry is pruned; the recent one and the new one remain.
    assert len(series) == 2
    assert series[-1]["commit"] == "abc1234"
    assert series[-1]["metrics"] == {"a.wall_seconds": 11.0}
    assert series[-1]["runner"] == "pinned"


def test_run_record_shape() -> None:
    rec = tripwire.run_record({"a.wall_seconds": 1.0}, runner="pinned", now=NOW)
    assert rec["runner"] == "pinned"
    assert rec["timestamp"] == NOW.isoformat()
    assert rec["metrics"] == {"a.wall_seconds": 1.0}
    assert "commit" not in rec  # omitted when not supplied
