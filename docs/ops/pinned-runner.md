# Runbook — the pinned benchmark runner + regression tripwire

Xtalate's performance corpus (`python -m benchmarks`, MASTER_SPEC Part 8 §4) is **measured, not
gated**: it reports wall-time and peak-RSS against the spec budgets but never fails a build on an
absolute-time breach, because shared CI runners are too noisy for an absolute bound to hold week to
week. The trustworthy gate is *relative*: the **>20% regression tripwire** compares each run against
the **median of the trailing 14 days on the same runner**. For that median to mean anything, the runs
must happen on **fixed silicon** — a **pinned** self-hosted runner.

This runbook is how a maintainer stands that runner up and turns the tripwire on. Until it is done,
the tripwire job is *skipped* (never queued against a runner that does not exist, never red), and the
nightly benchmark step keeps publishing the measured-only series on `ubuntu-latest` so the trend
stays visible.

## The performance targets (Part 8 §4)

The tripwire watches for *regressions*; these are the *absolute* budgets the run should also meet on
the pinned runner (reported by the harness, cited as the §6-item-5 release evidence):

| Benchmark | Wall-time budget | Peak-RSS budget |
|---|---|---|
| `parse_xdatcar_10k` (10,000 frames × 100 atoms) | ≤ 30 s | ≤ 2 GiB |
| `convert_xdatcar_to_extxyz_10k` (full pipeline + validation) | ≤ 90 s | ≤ 2 GiB |
| `convert_extxyz_roundtrip_1k` (1,000 × 1,000 identity round-trip) | ≤ 60 s | ≤ 3 GiB |
| `frame_limit_ceiling` (100,000-frame stream) | completes (sub-linear memory) | measured-only |
| `preflight_latency` (diff on a parsed 10k-frame object) | ≤ 1 s (`preflight_seconds`) | measured-only |

A budget breach is *reported* by `python -m benchmarks`; a **regression** (>20% over the median) is
what the tripwire *fails on*.

## One-time setup

### 1. Choose the hardware

Any machine you control and will keep stable: a dedicated cloud VM of a fixed instance type, a
physical box, or a lab server. **Do not** move the runner between machine classes — the whole point is
comparable timings. If the hardware changes, start a fresh series (see [Reset](#resetting-a-series)).

### 2. Register a self-hosted GitHub Actions runner

On the repository: **Settings → Actions → Runners → New self-hosted runner**, follow the platform
instructions, and give it **both** of these labels (the workflow targets `runs-on: [self-hosted,
xtalate-pinned]`):

```
self-hosted
xtalate-pinned
```

Keep the runner service running (the nightly cron fires at 07:00 UTC). Nothing about Xtalate needs
root; the runner just needs Python 3.13 available (the workflow installs the project into a venv via
`pip install -e ".[dev]"`).

### 3. Turn the tripwire on

Set the repository **variable** (Settings → Secrets and variables → Actions → **Variables**):

```
XTALATE_PINNED_RUNNER = true
```

That is the single switch that un-skips the `perf-tripwire` job in
[`.github/workflows/nightly.yml`](../../.github/workflows/nightly.yml). Leaving it unset (or anything
other than `true`) keeps the job skipped.

## What runs each night, once it is on

The `perf-tripwire` job:

1. Checks out the repo and installs the project.
2. Runs `python -m benchmarks --tripwire --runner xtalate-pinned --out benchmark-results` — the full
   corpus at spec scale, then:
   - compares each tracked metric against the median of the last 14 days in
     `benchmarks/history/xtalate-pinned.jsonl`,
   - **appends this run** to that series (pruning entries older than 60 days),
   - **exits non-zero on any >20% regression**, which fails the job.
3. Uploads the measurement artifact (`benchmark-results/`, the §6-item-5 evidence).
4. Commits the appended series back to the repo (`[skip ci]`), so tomorrow's median includes today.

A failed job (a crash, or a tripped regression) opens a tracking issue automatically, same as any
nightly failure.

### The first ~14 days are a baseline

A metric with no prior in-window data cannot regress — it *seeds* the series and passes. So a fresh
runner's first two weeks establish the baseline; the tripwire has real teeth once ~14 days of runs
have accrued. This is expected, not a gap: the harness's absolute budgets are the gate in the
meantime, and you can watch the uploaded series directly.

## Running it by hand

On the pinned runner (or any comparable machine), to reproduce what the nightly does:

```bash
python -m benchmarks --tripwire --runner xtalate-pinned --out benchmark-results
```

To measure without touching the series or gating (the safe default anywhere, including a laptop):

```bash
python -m benchmarks --out /tmp/bench
```

`--tripwire` **requires** `--runner` (or `$XTALATE_BENCH_RUNNER`) and **refuses `--smoke`**, so a
casual run can never write to a pinned series or compare against micro-scale numbers by accident.

## When the tripwire trips

A trip means a tracked metric got **more than 20% slower / heavier** than its two-week median. The
fix is to **investigate the regression**, not to quiet the tripwire:

- **Do** read the job log — `format_report` prints the current value, the median, and the ratio per
  metric — then bisect the change that caused it.
- **Do not** widen `--threshold`, shrink `--window-days`, or hand-edit / delete lines from the series
  to make the job green. That inverts the gate exactly as lowering the coverage floor would. The
  series file carries the same "never edit to hide a regression" rule in
  [`benchmarks/history/README.md`](../../benchmarks/history/README.md).

If a regression is *intentional and accepted* (a deliberate trade-off), record why in the change that
introduces it; the median absorbs it within ~14 days as the new normal, and the tripwire re-arms
around the new baseline on its own.

## Resetting a series

If you change the pinned hardware (or the benchmark definitions change enough that old numbers are not
comparable), delete the runner's series file and let it re-baseline:

```bash
git rm benchmarks/history/xtalate-pinned.jsonl
git commit -m "chore(benchmarks): reset pinned series (hardware change)"
```

The next nightly run seeds a fresh baseline. Note the reason in the commit — a silent reset looks
exactly like hiding a regression.
