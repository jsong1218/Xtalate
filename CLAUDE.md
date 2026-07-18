# CLAUDE.md — Xtalate Project Context

> Load this file at the start of every Claude Code / Claude chat session working on Xtalate. It is a compressed index of `docs/MASTER_SPEC.md` (the full constitution — a single edited document, *not* an assembly of standalone files; see the document-family section below). If anything here conflicts with a doc in `docs/`, **the doc wins** — this file is a map, not the territory. If a later-uploaded doc contradicts an earlier one, flag the discrepancy; do not silently pick one.

> **Status (refreshed Revision 1.16 + post-v0.3 architectural review, July 2026).** **v0.1–v0.3 are feature-complete (version `0.3.0`; the git tag and PyPI/GitHub publish remain the maintainer's pending manual step, D52).** v0.1 shipped the full spine — parse → pre-flight → recovery → export → report → validation — plus the Information Discovery Engine and the `xtalate` CLI for four formats (XYZ, extXYZ, POSCAR, CONTCAR); v0.2 (M7–M11, Revisions 1.8–1.13, D-log through D55) completed the Part 4 §3.3 recovery catalog, the velocity/mass recovery family, the Capability-Matrix-driven round-trip matrix (+ PyYAML), the `hypothesis`-driven report-completeness property test, golden-corpus governance, and the contributor surface — see `CHANGELOG.md` `[0.2.0]`. v0.3 — **"Trajectories at Scale"**, complete: **M12** made pipeline memory **sub-linear in frames** via the frame-chunked streaming core (`sdk/streaming.py`, `PresenceAccumulator`, `ConversionEngine.convert_stream`/`convert_stream_select`, streaming validation; "chunking changes memory, never truth" — the streamed report is proven identical to the materialized one; D56, `docs/MEMORY_CEILING.md`); **M13** added the **XDATCAR** streaming-first parser/exporter (fixed-cell + NpT per-frame-cell forms, `timestep = None` honesty, explicit `truncate_at_last_valid_frame` recovery; D57); **M14** added the **ASE `.traj`** parser/exporter with the default-laundering suite (ASE's manufactured zero cell/momenta/empty constraints → `None`; stress carried verbatim in `custom_per_frame`, D18; ASE version in provenance, D58–D59) and made the spec's worked example executable; **M15** landed the benchmark corpus (`python -m benchmarks`, measured-not-gated) and the PR/nightly matrix split (`.github/workflows/nightly.yml`: full n×n round-trip matrix, benchmarks, extended `hypothesis`, `pip-audit`); **M16** implemented **entry-point plugin discovery** (`xtalate.registry`, groups `xtalate.parsers`/`xtalate.exporters`, additive third pass in `default_registry()`, fails loudly) proven against the real installable `xtalate-toyfmt` fixture in CI (D60–D61), and cut the **`0.3.0`** release (Revision 1.16). **Six of the seven Phase-1 formats are registered; CIF is v0.4.** A post-`0.3.0` architectural review then fixed the XDATCAR Cartesian scale-factor defect, enforced the declaration-`format_id` check, attributed discovered-plugin collisions to their entry point (D62), gave the CLI a clean broken-plugin surface, brought `registry`/`_time` under the import-linter contract, and routed eligible `xtalate convert` runs through the streaming engines so the CLI inherits the M12 memory bound (D63) — see `CHANGELOG.md` `[Unreleased]`. The map below is current against Revisions 1.3–1.16 and `docs/DECISIONS.md` **D1–D63**. Mission, principles (P1–P6), the Mission Scope & Non-Goals above, glossary, architecture, the absence convention, tech stack (a *destination*, not the current dependency set), and API conventions remain binding. For build-time rationale read the MASTER_SPEC Preface revision log and the **D-log through D63**; per-version execution lives in `docs/IMPLEMENTATION_PLAN_v0.1.md`–`_v1.0.md`.

## Mission

> **Xtalate is the trusted translation layer between computational chemistry file formats — a converter that tells you exactly what it kept, what it lost, and why.**

Guiding philosophy: **never silently lose scientific information.** Litmus test for any design decision: *if a user diffed the source and output files by hand, would anything surprise them that Xtalate didn't already tell them about?* If yes, the design is wrong.

## Mission Scope & Non-Goals — binding (MASTER_SPEC §3–§4)

Xtalate does **one thing**: **loss-aware, fully transparent file conversion.** Guard the scope — resist feature creep that dilutes that focus. Authoritative statement lives in MASTER_SPEC Part 0 §3 (Scope) and §4 (Non-Goals); this is the always-loaded reminder.

- **Xtalate is NOT** a molecular-dynamics package, a DFT/quantum engine, a molecular editor, or a visualization-first application. It stores and translates data computed elsewhere; it never integrates equations of motion, computes energies, edits structures, or centres the product on rendering.
- **Visualization, File Repair, Analysis, and an AI Assistant are deferred *Secondary Goals* (§3.2), not core work.** Each is a *consumer* of the Canonical Model and reports — it attaches later at a defined seam (**P6**). Do not build these into the core, and do not add convenience features that only serve them. When a request drifts toward viewing/MD/editing/analysis, name it as Secondary-Goal scope and redirect.
- **Every augmentation is reported in plain language.** Anything Xtalate adds (filled masses, inferred symbols, a fabricated lattice, generated velocities) is recorded as an Assumption + `supplied` entry and rendered in the Conversion Report — e.g. *"Filled masses for 18 atoms using IUPAC standard atomic weights."* Never a silent fill (**P1**, **P4**).
- **No unrequested transformation — even a standard one — if it obfuscates or hides information (`docs/DECISIONS.md` D43).** Recovery fabricates *exactly* what the user asked and nothing more. Worked precedent: `missing_velocities=maxwell_boltzmann` emits the **raw** MB sample and does **not** remove centre-of-mass drift (an MD-engine convenience that would be a silent, unannounced change). Leave such steps to the downstream engine, or make them a separate explicit, recorded choice.

## Design Principles (P1–P6) — binding, referenced by ID in every doc

| ID | Principle |
|----|-----------|
| **P1** | Every loss is reported, never assumed. "The user probably doesn't need X" is never a valid reason for silence. |
| **P2** | No parser talks to another parser. All translation flows through one Canonical Model: `Native File → Canonical Object → Target Format`. No format-to-format shortcuts, ever. |
| **P3** | Absence is information. The schema distinguishes "never present in the source" (`None`) from "present with value zero/empty." |
| **P4** | Recover explicitly, never guess. Missing-but-required data is supplied only through an explicit Recovery Workflow, recorded as an Assumption. |
| **P5** | Know the formats before converting. The Capability Matrix predicts preservation/loss *before* conversion; Validation verifies it *after*. |
| **P6** | Extensibility over optimization. New formats/features attach at defined seams without core redesign; performance is reclaimed later behind stable interfaces. |

One sentence to carry into every doc: **a conversion you can't audit is a conversion you can't trust.**

## Binding Glossary (use these terms verbatim; never coin synonyms)

| Term | Meaning |
|---|---|
| **Canonical Model / Canonical Object** | The single internal schema every parser writes to and every exporter reads from (defined in `02_Canonical_Data_Model.md`). |
| **Parser** | Reads exactly one native format → produces a Canonical Object. Never writes files, never calls another parser, never defaults an absent field. |
| **Exporter** | Reads a Canonical Object → writes exactly one native format. Never reads native files. |
| **Capability Matrix** | Per-format, per-field data structure declaring what each format can/cannot express; drives loss prediction. |
| **Information Discovery Engine** | Inspects an arbitrary file and reports what's present/absent (✓/✗ per canonical field) without converting it. |
| **Recovery Engine / Recovery Workflow** | Offers explicit, user-chosen ways to supply data a target format requires but the source lacks; every choice becomes an Assumption. |
| **Conversion Report** | Structured, machine-readable record of what a conversion kept, dropped, transformed, or assumed. |
| **Validation Report** | Post-conversion re-parse-and-diff result against the original Canonical Object, within tolerance. |
| **Discovery Report** | Output of the Information Discovery Engine. |
| **Provenance** | Canonical Model's record of source software, parser version, and full conversion history (incl. all Assumptions). |
| **Plugin SDK** | Stable interface for third-party parsers/exporters/analysis modules; first-party formats hold no privileged API. |
| **Round-trip** | `Format A → Canonical → Format B → Canonical`, diffed within tolerance; primary strategy for catching silent bugs. |
| **Phase 1 formats** | The seven formats: XYZ, extXYZ, CIF, POSCAR, CONTCAR, XDATCAR, ASE trajectory. (Under the roadmap ladder these do not all land in the "MVP": roadmap v0.2's MVP is four of them — XYZ, extXYZ, POSCAR, CONTCAR, the v0.1 set — and all seven complete at roadmap v0.4. Say "the seven Phase 1 formats," not "the seven MVP formats.") |

## Architecture at a Glance

Single spine, four advisory subsystems that guide but never bypass it:

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                            ↑        ↓
                        Information Discovery   Capability Matrix
                        Recovery Engine (explicit only) → Validation Engine
```

- **Format Sniffer** — identifies format + confidence, selects a parser.
- **Parser layer** (one per format) — must not read another format or talk to another parser.
- **Canonical Object** — the only thing that crosses the parser/exporter boundary.
- **Capability Matrix** — tells the exporter what the target can hold *before* it writes.
- **Recovery Engine** — fills required-but-missing fields only with explicit user consent, recorded as an Assumption.
- **Validation Engine** — re-parses the output and diffs it against the source Canonical Object.
- **API layer** (`backend/`, FastAPI) — thin; validates requests, manages jobs/storage; contains no scientific logic.
- **Web UI** (`frontend/`, Next.js) — presents the workflow and renders reports faithfully; never re-implements conversion logic or hides losses.

## Canonical Model — Absence Convention (P3), normative

| State | Representation | Meaning |
|---|---|---|
| Absent | `None` | Source file did not contain this information at all. |
| Present | Actual value (incl. zeros) | Source file contained it; the value is the value. |

Parsers are forbidden from defaulting — no zero velocities, no identity lattice, no `energy = 0.0` invented to fill a gap. Schema categories: Geometry, Simulation Cell, Trajectory, Dynamics, Electronic Information, Simulation Metadata, Provenance, User Metadata. Modeled as pydantic v2-style; NumPy arrays in memory, nested JSON lists on the wire; internal coordinates and unit conventions are defined normatively in `02_Canonical_Data_Model.md` — treat field names there as final.

## Tech Stack (rationale lives in `01_Architecture.md §4`)

> These are destination choices for the versions that need them (Service in v0.5, Web UI in v0.6), not the current dependency set. Through v0.3 the library + CLI is pure Python: pydantic + numpy, ASE (the sole scientific dependency, backing extXYZ and the ASE `.traj` format — pymatgen was rejected; see `docs/DECISIONS.md` D4, D7), and PyYAML (custom tolerance tables + golden-corpus manifests, v0.2/M9).

| Layer | Choice |
|---|---|
| Frontend | Next.js + React + Tailwind |
| Backend | FastAPI (Python — must be in-process with ASE/pymatgen) |
| Scientific core | ASE + pymatgen |
| Future visualization | Mol* (secondary goal, not MVP) |
| Relational DB | PostgreSQL (JSONB for report bodies) |
| Blob storage | S3-compatible object storage, lifecycle-expiring |
| Job queue | RQ on Redis |

## Repository Shape (current v0.3 layout)

> The pre-implementation architecture review rejected a solo-maintainer monorepo of separately-packaged components as unnecessary overhead (`docs/ARCHITECTURE_REVIEW.md` §4.1; `docs/DECISIONS.md` D1). The shipped layout is **one package** in a `src/` layout — no per-component `pyproject.toml`s. `frontend/` and `backend/` do not exist yet; they arrive with the versions that need them (Service at roadmap v0.5, Web UI at v0.6). Entry-point plugin discovery **shipped in v0.3** (M16): third-party distributions advertise plugins under the `xtalate.parsers`/`xtalate.exporters` entry-point groups, and there is no `plugins/` directory — the proof plugin lives at `tests/fixtures/xtalate_toyfmt/` as its own installable distribution. `docs/MASTER_SPEC.md` Part 1 §5 is the authoritative tree.

```
src/xtalate/
  schema/         Canonical Model; depends on nothing else in xtalate/  (a.k.a. "canonical-schema")
  sdk/            stable parser/exporter base classes + capability models + streaming interface (a.k.a. "plugin-sdk")
  parsers/        one per format (6: xyz, extxyz, poscar, contcar, xdatcar, ase_traj); depends only on schema + sdk
  exporters/      one per format; depends only on schema + sdk
  capabilities/   Capability Matrix: assembles + queries declarations       (a.k.a. "capability-matrix")
  discovery/      Information Discovery Engine + Format Sniffer + Discovery Report
  conversion/     Conversion Engine — orchestrates the above + Conversion Report (incl. convert_stream)
  recovery/       Recovery Engine + workflows (preset-only until the v0.5 Service)
  validation/     Validation Engine + Validation Report (batch + streaming)
  cli/            thin argparse presenter: inspect / convert / validate / capabilities
  registry.py     composition root: default_registry() = built-ins + entry-point discovery (v0.3 M16)
  _time.py        the one UTC-timestamp helper (bottom layer of the import contract)
benchmarks/       Part 8 §4 benchmark harness (python -m benchmarks); measured, not coverage-gated
examples/         runnable end-to-end library + CLI samples
tests/            golden/, roundtrip/, streaming/, property/, fixtures/xtalate_toyfmt/, and per-subpackage suites
docs/             the doc family this file indexes
```

Dependency direction is strict and acyclic — enforced physically by an `import-linter` `layers` contract (`pyproject.toml`; since the post-v0.3 review it also covers `registry` and `_time`), run with ruff + mypy --strict + pytest on every PR (`docs/DECISIONS.md` D5). This is what enforces **P2**. The descriptive names in parentheses (`canonical-schema`, `plugin-sdk`, `capability-matrix`) are the prose labels used across the spec; the tree gives the import-name mapping.

## API Conventions (full spec in `06_API.md`)

- All endpoints under `/v1/`. Path-prefix versioning; additive changes are non-breaking; new formats/scenarios are *values*, not new endpoints.
- Long-running operations (`inspect`, `convert`, `validate`) are **async jobs**: submit → poll `/v1/jobs/{job_id}` → retrieve result.
- Job states: `queued → running → completed | failed | cancelled`, plus `queued → failed` (dequeue-precondition failure, Revision 1.1) and `running → awaiting_recovery → running | expired`. An expired `awaiting_recovery` job resolves to a **refused** conversion, never a silently applied default.
- **A refusal is not an HTTP error.** A conversion the engine declines is a completed job whose `ConversionReport.status == "refused"` — HTTP 200.
- Single error envelope for all non-2xx responses: `{ error: { code, message, details, request_id, documentation_url } }`. Codes are stable machine strings (e.g. `UNKNOWN_FORMAT`, `PARSE_ERROR`, `VALIDATION_ACK_REQUIRED`, `JOB_ALREADY_TERMINAL`).
- Response bodies embed the pydantic report models verbatim (`DiscoveryReport`, `ConversionReport`, `ValidationReport`) — no parallel DTOs.

*(This describes the v0.5 Service layer's target contract; there is no API yet in v0.1.)*

## Documentation Set

> `docs/MASTER_SPEC.md` is edited directly as the single source of truth (Revision 1.2, Preface); the standalone `00`–`10` `.md` files named in older prose **never existed as separate committed files** — do not create or assume them. The Part numbering (`04 §3.3` = "Part 4 §3.3") survives only as a stable citation scheme inside the one document. The document family that actually exists:

- **`docs/MASTER_SPEC.md`** — the constitution (Parts 0–10 + Appendices; Preface revision log runs Revisions 1.1–1.16). Start here; use its Table of Contents.
- **`docs/DECISIONS.md`** — build-time decisions log, **D1–D63**, each with a rejected alternative and a standing-rules note at the top.
- **`docs/ARCHITECTURE_REVIEW.md`** — the accepted pre-implementation review (its acceptance is MASTER_SPEC Revision 1.2).
- **`docs/Incremental_Roadmap_v1.0.md`** — the solo-developer version ladder (v0.1–v0.7); carries a Revision 1.6 staleness banner over its execution detail, ladder still binding.
- **`docs/IMPLEMENTATION_PLAN_v0.1.md` … `_v1.0.md`** — per-version execution plans, milestones **M0–M38**, each superseding the roadmap's execution prose for its version.
- **`docs/DOCS_CONSISTENCY_REVIEW_2026-07.md`** — the post-v0.1 corpus consistency review (findings C1–C11) the Revision 1.6/1.7 refresh implemented.
- **`docs/MEMORY_CEILING.md`** — the M12 streaming memory model and the M15 benchmark methodology (D56).
- **`docs/M14-M16_SLICE_PLAN.md`** — the v0.3 tail-slice execution log (M14/M15/M16, one importable slice at a time); historical now that v0.3 is complete.

> Not committed to this repo (external, historical): `Xtalate_Doc_Prompts.md` — the prompt set that generated the original drafts; superseded by the single-source-of-truth model, do not run it or create the standalone files.

## Working Rules for This Project

- **Run the lint gate before every commit/PR.** CI (`.github/workflows/ci.yml`) runs, in order, `ruff check .`, `ruff format --check .`, `mypy`, `lint-imports` (the import-linter P2 contract), then installs the toyfmt proof plugin (`pip install --no-deps ./tests/fixtures/xtalate_toyfmt` — its four end-to-end tests skip when it is absent) and runs `pytest`, on Python 3.11 and 3.13. Run all five locally (from the `.venv`: `source .venv/bin/activate`) before pushing — `ruff format --check` (the format case) fails independently of `ruff check` (the lint case), so a green `ruff check` does **not** mean formatting is clean. If `ruff format --check` reports files, run `ruff format .` to fix them. A separate `nightly.yml` runs the full n×n round-trip matrix (`XTALATE_FULL_MATRIX=1 pytest -m nightly`), the benchmarks, the extended `hypothesis` profile, and `pip-audit`.
- **Terminology is binding.** Reuse exact field names, endpoint paths, report field names, and component names already established. If a name seems wrong, say so explicitly and explain why — never rename silently.
- **Write for an isolated reader.** Every doc must stand alone for a contributor or a planning agent who has not read the master prompt directly, while staying consistent with the rest of `docs/`.
- **Justify nontrivial decisions.** Name at least one reasonable rejected alternative for each nontrivial architectural or design choice.
- **No silent data loss, ever — including in the docs themselves.** Any design that could cause silent loss must be called out explicitly, not glossed over.
- **MVP discipline.** Favor maintainability, correctness, and extensibility over convenience; don't overengineer Phase 1, but never foreclose Secondary Goals — name the extensibility seam they'd attach to.
- **Scope discipline.** Produce only the file(s) a given prompt asks for. Do not pad a doc with content that belongs in a different doc file.
- **Format.** Professional Markdown; Mermaid for all diagrams (GitHub-renderable); directory trees where relevant; no marketing language — this is engineering documentation, not a pitch.
- **No AI attribution in commits.** No `Co-Authored-By` AI trailer, no "Generated with …" line, and no AI listed as author or contributor in commit metadata, `CITATION.cff`, or release notes — the human maintainer is the author of record on every commit an agent creates or assists with. (`docs/MASTER_SPEC.md` Preface; `docs/DECISIONS.md` D10.)
- **Never commit secrets.** No API keys, tokens, database credentials, or other secrets are ever committed to this repository, in code, config, fixtures, or commit messages — not even temporarily, not even in a since-reverted commit (git history is not a safe place to "fix it later"). Secrets are supplied only via environment variables or an untracked local file (`.env`, already gitignored) and referenced by name in code, never inlined. Before staging or committing, check `git status`/`git diff` for anything that looks like a credential — including in filenames that look innocuous — and stop to ask if unsure. If a secret is ever accidentally committed, the fix is rotation (invalidate the leaked credential) *and* history rewrite, not just a follow-up commit that deletes it. There are no secrets in the v0.1 codebase (pure-Python library + CLI, no network calls, no credentials); this rule exists ahead of need because v0.5 (Service layer: database, object storage, hosted-instance API keys) is exactly where a leak would first become possible, and the discipline should already be established by then.

