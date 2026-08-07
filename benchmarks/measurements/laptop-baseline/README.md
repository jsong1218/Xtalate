# Laptop baseline measurement — **NOT the release evidence**

> ⚠️ **This is a placeholder, not the §6-item-5 performance evidence.** It was produced by
> `python -m benchmarks --out …` on the maintainer's **laptop** (macOS, Apple silicon), not on the
> pinned runner. The v1.0 release evidence is the pinned-runner run — see
> [`docs/ops/pinned-runner.md`](../../../docs/ops/pinned-runner.md). Replace this directory's
> `results.json`/`results.csv` with the pinned-runner artifact before the release audit (M38), or
> point the audit at the uploaded `benchmark-results-pinned` artifact from the nightly job.

## Why it exists

M37 S2's deliverable is a *committed measurement artifact* plus a *working tripwire*. The tripwire and
its runbook are the durable in-session work; a real pinned-runner number is a ⏳ maintainer step
(register the runner, flip `XTALATE_PINNED_RUNNER`). Until that lands, this laptop run is the honest
stand-in: it proves the harness produces the artifact and that every Part 8 §4 budget is met with
generous headroom on developer-class hardware — it is **not** a claim about the release target's
timings.

## What it recorded (`results.json` / `results.csv`, this run)

| Benchmark | Wall (s) | Budget | Peak RSS | Budget | Verdict |
|---|---|---|---|---|---|
| `parse_xdatcar_10k` | 2.18 | ≤ 30 s | 0.152 GiB | ≤ 2 GiB | ✅ |
| `convert_xdatcar_to_extxyz_10k` | 10.26 | ≤ 90 s | 0.087 GiB | ≤ 2 GiB | ✅ |
| `convert_extxyz_roundtrip_1k` | 13.16 | ≤ 60 s | 0.131 GiB | ≤ 3 GiB | ✅ |
| `frame_limit_ceiling` | 12.47 | completes | 0.084 GiB | measured-only | ✅ completes, sub-linear |
| `preflight_latency` | — | — | 0.154 GiB | — | ✅ `preflight_seconds` = 0.033 s (≤ 1 s) |

Every budget met; the 100,000-frame ceiling completes with a peak RSS far below the materialized cost
(the sub-linear-memory demonstration). These are laptop numbers — comfortably inside the budgets, as
expected — and are recorded only to show the artifact shape and that nothing is red, not as the pinned
measurement.

This directory is **not** a tripwire series (that is `benchmarks/history/<runner>.jsonl`, per-runner,
appended only by the pinned nightly job). It is a one-off snapshot.
