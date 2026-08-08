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

**Status:** in progress (S1–S3 landed: §6 items 1–5/6). Last updated: 2026-08-08.

---

## §6 finish-line summary

| §6 item | Claim | Verdict | Slice |
|---|---|---|---|
| **1** | Seven-format golden coverage; 30-day nightly-matrix green | ✅ coverage + matrix green now · ⏳ 30-day clock (4/30) | S1 |
| **2** | Completeness property test passes with **zero waivers** | ✅ confirmed (grep clean; 570 green) | S1 |
| **3** | Frozen contracts: schema 1.0.0 + migration; SDK + reference-plugin canary; `/v1` OpenAPI artifact | ✅ all present + green | S1 |
| **4** | Stranger reproduces 3 worked examples on 4 surfaces from public docs | ✅ reproduced in-session (4/4 surfaces) · ⏳ true-stranger run (procedure committed) | S3 |
| **5/6** | Honesty: risk register tracked; README SemVer; **ATTRIBUTIONS.md complete + CI-enforced** | ✅ ATTRIBUTIONS.md landed + CI-enforced; README/risks verified | S2 |
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

**Claim.** A non-author reproduces the three worked examples (Part 2 §8 — discovery; Part 4 §5 —
ASE-trajectory→POSCAR conversion with recovery; Part 5 §6 — validating that conversion) on all four
surfaces from the *published* docs only.

**Evidence (✅ in-session · ⏳ true-stranger run).** All three examples were reproduced in-session on
all four surfaces from the published docs alone (`quickstart.md`, `cli.md`, `API.md`,
`DEVELOPER_GUIDE.md`, the Web UI) — never `docs/private/`. The three examples form one story
(discover → convert-with-recovery → validate); the reproduction inputs were built from published
materials (a 2-frame XYZ + a fractional POSCAR typed inline, and a 10-frame water `relax.traj` with
forces/energy and no cell built by a short ASE snippet — ASE being a declared dependency), so the run
needs no repository fixtures.

| Surface | Path driven | Result |
|---|---|---|
| **Library** | `default_registry()` + `DiscoveryEngine.discover` / `ConversionEngine.convert(recovery_choices=…)` (`API.md §2`) | ✅ discovery present=`[atoms.symbols, atoms.positions]`; conversion preserved symbols+positions, removed forces+total_energy+extra-frames, supplied lattice+pbc (both `A2`); validation `passed`, 9 checks |
| **CLI** | `xtalate inspect`; `xtalate convert --to poscar --recover frame_selection=last --recover missing_lattice=bounding_box,padding_ang=5.0` (`cli.md`) | ✅ same accounting; A1/A2 assumptions in plain language; validation `passed` (8 pass + `numeric_field_fidelity` reported `skipped`); exit `0` |
| **API** | `docker compose up`; `POST /v1/upload` → `/v1/inspect` → `/v1/convert {allow_recovery}` (pauses `awaiting_recovery`) → `/v1/jobs/{id}/recovery/preview` → `/recovery` → `/download/{cid}` → `/conversions/{cid}` (`API.md §5.2`) | ✅ pause exposed both unresolved scenarios; durable record served `conversion_report.status="completed"` + `validation_report.status="passed"`; assumptions `origin:"user"` (interactive path) |
| **Web UI** | landing → upload → inspect → preview loss → decide recovery → record → download, against the live stack | ✅ confirmed live + the `recovery-flagship` Playwright e2e journey ("upload → convert → pause → decide → preview → record, the trajectory→POSCAR flagship") passes; full e2e suite **24/24 green** on-branch |

**Docs gap found and fixed (a release blocker, §6 item 7 in spirit).** The one published-docs defect a
stranger would hit: `quickstart.md` used `POST /v1/files` for upload, which **does not exist** — the
only `/v1/files/{id}` route is `DELETE`. Verified live: `POST /v1/files` → **404**, `POST /v1/upload`
→ **201** (and `README.md` + `SECURITY.md` already used the correct `/v1/upload`). Fixed in
`quickstart.md` to `POST /v1/upload`, with a pointer to the full `API.md §5` flow. Docs-only; no
`src/xtalate/` change.

**Notes (not defects, recorded for honesty):**
- The service `curl` examples (`API.md §5.2`, `quickstart.md`) assume **`jq`** — a standard curl+JSON
  idiom, not a Xtalate requirement. The committed reproduction procedure names it as a prerequisite
  with the raw-JSON fallback, so a stranger without `jq` is not blocked.
- The *private*-spec §5 worked example lists two conversion warnings (a coordinate-representation
  warning alongside the precision warning); the shipped engine emits the precision warning only. This
  is a private-spec-example detail, **not** a published-docs promise (the published `API.md`/UI describe
  warnings generically), so it is neither a released-docs drift nor an engine change — recorded here and
  carried to S4's spec-side reconciliation.

**Committed artifacts.** [`reproduction-procedure.md`](reproduction-procedure.md) — the self-contained,
published procedure a real non-author follows to reproduce all three examples on all four surfaces
from public docs only (builds its own inputs; states the expected result for each surface). This is the
⏳ artifact the maintainer hands to an actual stranger.

**⏳ Maintainer step.** Hand `reproduction-procedure.md` to a real non-author and capture their run.
The in-session reproduction above is the evidence that the procedure is followable and the docs
support it; the true-stranger execution is the wall-clock/human half that a coding session cannot be.

---

## §6 items 5/6 — Honesty checks

**Claim.** The honesty half of the finish line: the flagged risks are tracked; the README's SemVer
promises and self-hosting posture are present and correct; and a **complete, CI-enforced** project-level
`ATTRIBUTIONS.md` records every dependency's license.

### Root `ATTRIBUTIONS.md` — complete + CI-enforced (✅ — the one real gap, now closed)

The one genuine gap the audit found: a **project-level** attributions file was **absent** — only
`tests/golden/ATTRIBUTIONS.md` (scoped to test *data*) existed. Closed in S2:

| Artifact | Evidence | Verdict |
|---|---|---|
| **Root `ATTRIBUTIONS.md`** (new) | Covers Xtalate's own Apache-2.0 license; the 4 core runtime deps + licenses (pydantic MIT, numpy BSD-3-Clause, ASE LGPL-2.1-or-later, PyYAML MIT); the 10 `service`-extra deps + licenses (FastAPI/pydantic-settings/SQLAlchemy/alembic/redis MIT, uvicorn BSD-3-Clause, boto3/python-multipart Apache-2.0, rq BSD-2-Clause, psycopg LGPL-3.0-only); the frontend npm license posture (permissive tree, lockfile-authoritative); the ASE-sole-scientific-dependency note (D7) and honest LGPL-as-library note for ASE + psycopg; a pointer to the test-*data* attributions (`tests/golden/ATTRIBUTIONS.md` + `NOTICE`). Licenses taken from installed package metadata, not guessed. | ✅ complete |
| **Completeness check** | `tests/test_attributions.py` parses `pyproject.toml` (`[project].dependencies` + the `service` extra) and asserts every distribution name appears in `ATTRIBUTIONS.md`, matched on token boundaries (so `pydantic-settings` cannot spuriously satisfy `pydantic`). Reads the file, not the venv → runs in the ordinary gate, no network. | ✅ present + green |
| **CI enforcement** | Collected by the existing `pytest tests` step in `.github/workflows/ci.yml` (same fold-in as the golden-corpus governance suite; the step comment now names it). Adding a dependency without its attribution row fails CI. | ✅ enforced |

### README SemVer promises + self-hosting posture (✅ verified — no change needed)

| Check | Evidence | Verdict |
|---|---|---|
| SemVer promises present + correct | `README.md` "Versioning and stability" (lines ~205–246): names the exact frozen public surface (canonical schema, the three report schemas, the plugin SDK ABCs, `/v1` + `docs/openapi.json`, documented CLI flags); "additive only within 1.x, breaks wait for 2.0"; the two-version-axis distinction (product version vs canonical `schema_version` 1.0.0); the "1.0.0 release follows a 30-day green-nightly window" gate. Matches MASTER_SPEC Part 10 §6 + the risk register R12. | ✅ present + correct |
| Self-hosting is the primary supported deployment | `README.md:28` states self-hosting is the primary supported deployment with `docker-compose.prod.yml`, an honest backup posture, and a zero-SaaS review, pointing to `docs/self-hosting.md` (M37 D132). | ✅ present + consistent |

No README change needed — verify-only, as S2 anticipated. (Any drift here would have fed S4; none found.)

### Risk-register status (✅ recorded)

The flagged risks (R1/R3/R7/R8/R10/R12 — the register's genuinely-open ⚠ items, MASTER_SPEC Part 10 §3)
and their current posture at the v1.0 finish line:

| Risk | Current posture at v1.0 | Tracking | Verdict |
|---|---|---|---|
| **R1** Silent data loss | Fully realized: absence convention, pre-flight prediction, the completeness property test (§6 item 2, zero waivers), post-hoc validation, UI anti-burying rules — all shipped and green. Residual (symmetric parser/exporter bugs passing their own round-trips) mitigated by golden + wild anchoring to external truth; corpus grows forever. | Standing (golden/wild corpus governance in CI) | ✅ mitigated as designed; residual is inherent, tracked by the ever-growing corpus |
| **R3** Unit mismatches | One canonical unit system; conversion only at boundaries; `provenance.source_units` recorded. Residual (ambiguous unit declarations, e.g. LAMMPS unit styles) is **post-1.0 per-format work** — the `recovery_hint` pattern exists; no ambiguous-unit format is in the Phase-1 seven. | Post-1.0 (per-format, on format admission) | ✅ no open Phase-1 exposure |
| **R7** Unsupported metadata | Verbatim carry-through (`simulation.extra`, `user_metadata`); drops named per key in `removed`. Residual (bytes preserved, not cross-format meaning) is inherent; the promotion path converts recurring extras to first-class fields over time. | Standing (promotion path on recurring cases) | ✅ mitigated; residual inherent |
| **R8** Large-trajectory performance | Retired for v1.0: frame-chunking **shipped** (v0.3 M12), the benchmark tripwire runs nightly (M37 >20% regression gate), memory bounds enforced via the frame ceiling. The "top schedule risk of v0.2" (chunking committed-but-unimplemented) is closed. | Standing (nightly benchmark tripwire) | ✅ closed for v1.0 |
| **R10** Security of uploaded files | Threat-decomposed controls shipped + reviewed (M37 security-review artifact): private buckets, authenticated streaming, size/rate/concurrency caps, files-as-data. Residual (dependency-inherited parser CVEs, e.g. ASE) mitigated by the nightly `pip-audit` + the worker sandbox; never eliminable. The M37 Dependabot sweep cleared all 12 advisories. | Standing (nightly pip-audit; Dependabot) | ✅ mitigated; residual never eliminable, actively watched |
| **R12** Extensibility / SDK stability | Retired at the freeze: the plugin SDK is **frozen at 1.0** (M35) and the reference plugin is the compatibility canary as a **hard CI gate** (M36, §6 item 3). The pre-1.0 "third-party plugins will break" honesty caveat is now satisfied by the freeze itself. | Standing (reference-plugin canary in CI) | ✅ closed by the freeze |

**Issue-filing note (no external post made).** Per the S2 plan, the default is this committed status
table naming each risk's posture; **no GitHub tracking issue is filed silently.** None of the six needs a
new tracking issue at v1.0 — R1/R7/R10 are standing residuals watched by existing CI gates, R8/R12 are
closed by shipped work, R3 is post-1.0 per-format work with no Phase-1 exposure. If the maintainer wants
any tracked as a GitHub issue, that is a maintainer step (external posting).

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
