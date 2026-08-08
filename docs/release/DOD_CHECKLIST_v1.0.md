# Xtalate v1.0 — Definition-of-Done Checklist (Part 10 §6)

> **What this is.** The v1.0 release review record. MASTER_SPEC Part 10 §6 is the finish line — *"this
> list is the finish line; nothing else is."* This document walks it line by line and resolves each line
> to a **committed evidence artifact**: a file, a passing test, a CI run, or a marked ⏳ maintainer step.
> The difference between "we're done" and "here is the proof we're done" is this artifact. The tag is
> pushed only after every line is green (or its ⏳ step executed).
>
> **Milestone M38** produces this document. It accretes across slices S1→S4 and is finalized in S5. The
> **release packaging** (version bump, CHANGELOG 1.0.0 entry, announcement, tag/publish) is **deferred to
> after a v1.0.0 architectural review** by an explicit maintainer decision (see the Deferred section);
> M38-in-session ships the *audit half* only. The package version stays `0.7.0` throughout M38.
>
> **Scope guard.** M38 makes **zero `src/xtalate/` engine changes** — it audits and records; it does not
> fix the engine (a real engine fix would restart the 30-day clock, and is a stop-and-escalate).

**Status:** in progress (S1 landed: §6 items 1–3). Last updated: 2026-08-08.

---

## §6 finish-line summary

| §6 item | Claim | Verdict | Slice |
|---|---|---|---|
| **1** | Seven-format golden coverage; 30-day nightly-matrix green | ✅ coverage + matrix green now · ⏳ 30-day clock (4/30) | S1 |
| **2** | Completeness property test passes with **zero waivers** | ✅ confirmed (grep clean; 570 green) | S1 |
| **3** | Frozen contracts: schema 1.0.0 + migration; SDK + reference-plugin canary; `/v1` OpenAPI artifact | ✅ all present + green | S1 |
| **4** | Stranger reproduces 3 worked examples on 4 surfaces from public docs | ⬜ pending | S3 |
| **5/6** | Honesty: risk register tracked; README SemVer; **ATTRIBUTIONS.md complete + CI-enforced** | ⬜ pending | S2 |
| **7** | docs↔code drift review as a release blocker | ⬜ pending | S4 |
| Release | CHANGELOG 1.0 entry, announcement, tag + publish | ⏳ **deferred** (post-v1.0.0-arch-review, then maintainer) | — |

Legend: ✅ verified with committed evidence · ⏳ maintainer/wall-clock step (documented, not silently skipped) · ⬜ not yet audited.

---

## §6 item 1 — Seven-format golden coverage + the 30-day matrix accounting

**Claim.** All seven Phase-1 formats have golden coverage; the nightly full n×n round-trip matrix shows
**≥30 consecutive green days** since the last engine-touching merge.

### Golden coverage (✅)

All seven Phase-1 formats have a golden corpus directory under `tests/golden/`, each governed by
`tests/golden/_governance.py` and exercised by a per-format golden suite:

| Format | Golden dir(s) | Suite |
|---|---|---|
| XYZ | `tests/golden/xyz/water-traj` | `test_corpus_governance.py` |
| extXYZ | `tests/golden/extxyz/co-in-cell` | `test_corpus_governance.py` |
| CIF | `tests/golden/cif/{nacl-fm3m, rutile-p42mnm, zno-hexagonal-p1, occupancy-and-cell-uncertainty}` | `test_cif_golden.py` |
| POSCAR | `tests/golden/poscar/nacl-primitive` | `test_corpus_governance.py` |
| CONTCAR | `tests/golden/contcar/co-md-restart` | `test_corpus_governance.py` |
| XDATCAR | `tests/golden/xdatcar/{si-single-configuration, si-npt-variable-cell, nacl-md-fixed-cell}` | `test_xdatcar_golden.py` |
| ASE `.traj` | `tests/golden/ase_traj/{water-single-molecule, co-relax-3frame}` | `test_ase_traj_golden.py` |

Plus `tests/golden/exfmt/water-monomer` — the M36 **reference plugin** (`exfmt`), which anchors the
plugin canary and enrols `exfmt` as a matrix source/target in the nightly run (not a Phase-1 format).

### The n×n round-trip matrix (✅ wired + green now)

The full matrix is wired in `.github/workflows/nightly.yml` (stage 1): it installs the reference plugin
(`pip install --no-deps ./plugins/example-format`) so `exfmt` is enrolled, then runs
`XTALATE_FULL_MATRIX=1 pytest -m nightly --no-cov`. `XTALATE_FULL_MATRIX=1` un-gates the `nightly`-marked
pairs (`tests/conftest.py`); the matrix generator is `tests/roundtrip/_matrix.py`. Every recent nightly
run completed **`success`**, so the matrix passed in each.

### 30-day clock accounting (⏳ maintainer — wall-clock gate)

The clock is **≥30 consecutive nightly greens since the last engine-touching merge**. The last
engine-touching merge is **M35** (schema `1.0.0` + the real migration in `src/xtalate/schema/`), merged
**2026-08-04 20:47** (PR #56). M36 (reference plugin, `plugins/`) and M37 (docs/tests/CI/benchmarks)
made **zero `src/xtalate/` changes**, so neither restarted the clock. M38 makes none either.

Nightly runs **after** the 2026-08-04 20:47 clock start (via `gh run list --workflow=nightly.yml`), all
`success`:

| Nightly (UTC) | Conclusion |
|---|---|
| 2026-08-05 09:35 | success |
| 2026-08-06 09:37 | success |
| 2026-08-07 08:11 | success |
| 2026-08-08 07:47 | success |

**Consecutive greens since clock start: 4 / 30.** (The 2026-08-04 09:37 nightly and everything earlier —
also an unbroken green streak back past 2026-07-18 — ran against the *pre-freeze* engine and do not count
toward the frozen engine's stability claim; the honest count is post-M35 only.)

**⏳ Maintainer step (wall-clock, cannot be executed in-session):** the tag waits until this reaches 30.
Projected earliest 30th consecutive green ≈ **2026-09-03** (30 nightlies from 2026-08-05), *provided* no
red intervenes and no engine-touching fix restarts the clock. Any `src/xtalate/` fix resets the count to
0. This gate is additionally downstream of the v1.0.0 architectural review and the release packaging
(see Deferred).

---

## §6 item 2 — Completeness property test, zero waivers

**Claim.** The report-completeness property test runs against every golden case and the generated corpus
with **zero waivers** — audited by grepping for skip/xfail markers, not by trusting memory.

**Evidence (✅).** Grep of the property suites (`tests/property/`) for waiver markers
(`skip`, `xfail`, `skipif`, `pytest.skip`, `@pytest.mark.skip`):

| Pattern | Hits | Verdict |
|---|---|---|
| `skip` / `xfail` / `skipif` in `tests/property/**` | 2 | Both are **docstring prose asserting the no-waivers rule** — `test_report_completeness.py:20` and `test_report_completeness_hypothesis.py:11` each literally state "never an `xfail`" (v0.2 standing rule 3). **No executable waiver.** |

Property suites present and run clean: `test_report_completeness.py`,
`test_report_completeness_hypothesis.py`, `test_fabricative_recovery_completeness.py` (+ `_strategies.py`,
`_generators.py`, `_properties.py`). Green-now run: `pytest tests/property/` → **all passed** (part of the
570-test evidence run below). Zero waivers, confirmed by audit not memory.

---

## §6 item 3 — Frozen contracts

**Claim.** Schema `1.0.0` + real migration (M35); stable SDK + reference-plugin canary (M36); `/v1`
OpenAPI artifact attached to the release.

**Evidence (✅).**

| Contract | Evidence | Verdict |
|---|---|---|
| **Schema `1.0.0`** | `src/xtalate/schema/models.py:40` (`SCHEMA_VERSION = "1.0.0"`), exported from `schema/__init__.py`; required field `schema_version` on the canonical object (`models.py:243`) | ✅ frozen |
| **Real `0.1.0 → 1.0.0` migration** | `src/xtalate/schema/migrations.py` (the registry + the step, D114); tested by `tests/schema/test_migrations.py` | ✅ present + green |
| **Stable SDK + reference-plugin canary** | `.github/workflows/ci.yml`: installs `./plugins/example-format` **before** `lint-imports` (part 1) and collects `plugins/example-format/tests/` as a **required** suite (`pytest tests plugins/example-format/tests`, part 2) — a hard CI gate (M36, D125). A core change that breaks `exfmt` fails CI. | ✅ hard gate + green |
| **`/v1` OpenAPI artifact** | `docs/openapi.json` (committed, 49999 bytes) — the versioned `/v1` REST schema; drift-guarded by `tests/backend/test_openapi_artifact.py` (regenerates from the FastAPI app and diffs against the committed file). **Release-attachable:** a stable committed file the eventual GitHub release attaches. | ✅ present + drift-guarded + green |

**Green-now evidence run** (2026-08-08, `pytest tests/property/ tests/schema/test_migrations.py
tests/backend/test_openapi_artifact.py plugins/example-format/tests/ -q --no-cov`):
**570 passed** (warnings are the known-cosmetic httpx2-TestClient + ASE/NumPy-2.5 deprecations, neither
in Xtalate code).

---

## §6 item 4 — Worked-example stranger reproduction (4 surfaces)

⬜ **Pending (S3).** Best-effort in-session reproduction of the three worked examples (Part 2 §8, Part 4
§5, Part 5 §6) on library, CLI, API, and UI from published docs only, plus a committed reproduction
procedure for a real non-author (⏳ stranger step). e2e-gated.

---

## §6 items 5/6 — Honesty checks

⬜ **Pending (S2).** Risk-register (R1/R3/R7/R8/R10/R12) status table; README §4.2 SemVer promises +
self-hosting posture verification; **root `ATTRIBUTIONS.md` complete + CI-enforced** (the one real gap —
absent today; only `tests/golden/ATTRIBUTIONS.md` exists).

---

## §6 item 7 — docs↔code drift review (release blocker)

⬜ **Pending (S4).** The accumulated MASTER_SPEC Revision-notes as the worklist; every published doc
diffed against shipped reality; every drift fixed in docs (a code drift → stop-and-escalate).

---

## Deferred to post-v1.0.0-architectural-review (⏳ maintainer, clock-gated)

By explicit maintainer decision this session (recorded in the M38 D-log, D133+), the **release packaging**
is deferred to *after* a v1.0.0 architectural review — following the project's standing rule that each
version's architectural review folds into that version before tagging. M38-in-session ships the audit
half only. The following are **not** done in M38 and are not silently skipped:

- **Version bump `0.7.0 → 1.0.0`** (`pyproject.toml`, `src/xtalate/__init__.py`) — at tag time.
- **CHANGELOG 1.0.0 release entry** — M38 leaves only an `[Unreleased]` audit note.
- **The v1.0 announcement** (what is frozen, what SemVer promises, what post-1.0 looks like — Part 10 §5).
- **`git tag v1.0.0` + publish** — PyPI, GHCR images, GitHub release with the OpenAPI artifact
  (`docs/openapi.json`) and the schema migration notes attached. Always the maintainer's manual step
  (D52), gated on the 30-day clock (§6 item 1).

Inherited ⏳ real-infra items from M37 (release checklist recurs on them): the pinned-runner benchmark,
the real-S3 lifecycle-expiry run, and the production `pg_dump` restore drill — all documented with
runbooks + placeholders under `docs/ops/`.
