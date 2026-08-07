# Benchmark history — the tripwire's rolling series

This directory holds the persisted performance series the **>20% regression tripwire**
(`benchmarks/tripwire.py`, M37 S2) reads and appends to. Each file is **one runner's** history:

```
history/<runner>.jsonl
```

One JSON object per line, one line per benchmark run:

```json
{"commit": "abc1234", "metrics": {"parse_xdatcar_10k.wall_seconds": 12.34, "parse_xdatcar_10k.peak_rss_bytes": 1234567890, "...": 0.0}, "runner": "xtalate-pinned", "timestamp": "2026-08-06T07:00:00+00:00"}
```

- **`runner`** — the pinned-runner identity, matching the filename. The tripwire only ever compares a
  run against *its own runner's* history, so the series stays on comparable silicon.
- **`timestamp`** — UTC, ISO-8601. The tripwire takes the median over the trailing **14 days**.
- **`metrics`** — flat `"<benchmark>.<metric>"` map: `wall_seconds` and `peak_rss_bytes` for every
  benchmark, plus any budgeted metric (e.g. `preflight_latency.preflight_seconds`). Lower is better
  for all of them, so a regression is always an increase.
- **`commit`** — the `GITHUB_SHA` the run measured, when available.

## How it is written

Only the pinned-runner nightly job appends here, via:

```bash
python -m benchmarks --tripwire --runner xtalate-pinned
```

That runs the corpus, compares against the trailing-median, appends the run (pruning entries older
than 60 days so the file stays bounded), and **exits non-zero on a >20% regression** — failing the
nightly job, which opens the tracking issue. A crashed run is never appended (it is not a comparable
data point).

**Never hand-edit or prune a series to make a red run green** — that inverts the gate exactly as
lowering the coverage floor would. A trip means: investigate the regression. See
[`docs/ops/pinned-runner.md`](../../docs/ops/pinned-runner.md) for the full runbook and for how to
seed a fresh runner's series.

Laptop and shared-CI (`ubuntu-latest`) runs must **never** be committed here — they are too noisy to
be a baseline. The `--tripwire` mode requires `--runner`/`$XTALATE_BENCH_RUNNER` precisely so a
casual `python -m benchmarks` cannot write to a pinned series by accident.
