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
| `parse_vasprun_10k` | 5.86 | ≤ 30 s | 0.186 GiB | ≤ 2 GiB | ✅ |
| `parse_outcar_10k` | 4.05 | ≤ 30 s | 0.170 GiB | ≤ 2 GiB | ✅ |
| `convert_outcar_to_extxyz_10k` | 18.13 | ≤ 90 s | 0.106 GiB | ≤ 2 GiB | ✅ |
| `convert_extxyz_roundtrip_1k` | 13.16 | ≤ 60 s | 0.131 GiB | ≤ 3 GiB | ✅ |
| `frame_limit_ceiling` | 12.47 | completes | 0.084 GiB | measured-only | ✅ completes, sub-linear |
| `preflight_latency` | — | — | 0.154 GiB | — | ✅ `preflight_seconds` = 0.033 s (≤ 1 s) |
| `parse_lammpsdump_10k` | 2.77 | ≤ 30 s | 0.178 GiB | ≤ 2 GiB | ✅ |
| `convert_lammpsdump_to_extxyz_10k` | 11.66 | ≤ 90 s | 0.087 GiB | ≤ 2 GiB | ✅ |

Every budget met; the 100,000-frame ceiling completes with a peak RSS far below the materialized cost
(the sub-linear-memory demonstration). These are laptop numbers — comfortably inside the budgets, as
expected — and are recorded only to show the artifact shape and that nothing is red, not as the pinned
measurement.

The three VASP-output rows (`parse_vasprun_10k`, `parse_outcar_10k`, `convert_outcar_to_extxyz_10k`)
were appended by the M44 measurement; `convert_outcar_to_extxyz_10k` is the flagship `convert OUTCAR
--to extxyz --validation-report` command through the CLI (streaming path), and it is green only because
M44-S1's streaming-validator carry fix (D168) landed first.

The two LAMMPS rows were appended by the M49 measurement (10⁴ frames × 100 atoms, the same generator
the M49-S2 gated streaming test uses). `convert_lammpsdump_to_extxyz_10k` is the deployment-format
flagship: `convert dump.lammpstrj --to extxyz --validation-report` through the CLI (streaming path),
green only because the M49-S2 streamed write-plan refinement (D185) landed first — a dump's
`:`-scoped per-atom customs (`lammps_dump:id`) are Removed per-key, and the streamed validation
expected side must mirror that classification or it false-fails where the materialized path passes.

This directory is **not** a tripwire series (that is `benchmarks/history/<runner>.jsonl`, per-runner,
appended only by the pinned nightly job). It is a one-off snapshot.
