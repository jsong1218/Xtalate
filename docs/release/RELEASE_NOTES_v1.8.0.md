# Xtalate v1.8.0 — Release Notes

> **Status: draft.** Prepared for the maintainer to attach to the GitHub release at tag time (D52).
> Nothing here is published until the maintainer tags and releases — `git tag v1.8.0` and the
> PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.8.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. v1.8 is
the **Analysis Plugin Surface** — a new *read-only* plugin kind that annotates its own namespace and
adds **zero fields** to the Canonical Object — so the mandatory `Schema version:` line above reads
`1.0.0`, not `1.1.0`. `operation="analyze"` was reserved vocabulary in the 1.x schema all along;
activating a documented reserved value changes no shape, and a schema number that incremented without
a schema change would be a version that lies. The honest statement is a package bump on a frozen
schema.

## Added

* **The `AnalysisPlugin` SDK, containment, and discovery (M68).** A third plugin kind on the frozen
  public SDK — `xtalate.sdk.AnalysisPlugin`: a `name`, a `version`, and one
  `analyze(canonical) -> Mapping[str, JsonValue]` method, with no lifecycle hooks, configuration
  language, or capability negotiation (D267). The runner `xtalate.sdk.run_analysis` makes two
  guarantees literal: **containment is enforced, not trusted** (D268) — the plugin is handed a deep
  copy, and only keys prefixed `"<name>:"` are merged into `user_metadata.custom_global`; any escape,
  any value the container cannot hold, or any exception is an `AnalysisError` with the caller's object
  returned untouched — and **every run is recorded** (D269) — one `ConversionRecord(operation="analyze")`
  naming the plugin, its version, and the keys it wrote. Discovery gains a third entry-point group,
  `xtalate.analysis`.
* **The composition reference plugin (M69).** `xtalate-analysis-composition`, its own installable
  distribution and a hard CI canary: element counts, a reduced Hill formula, and mass density —
  trivial science, exemplary honesty. Density is reported only when the source carries both a cell and
  masses; otherwise it is `null` with a `density_note` stating why, and masses are **never**
  fabricated (filling absent data is recovery's job — P3/P4, D270). An import-linter contract proves
  it builds only against `xtalate.sdk` and `xtalate.schema`.
* **The plugin inventory, the analyze surface, and the Analysis tab (M70).** You write a plugin once;
  three surfaces read the keys it wrote through the **same** engine, so they can never drift.
  `GET /v1/plugins` advertises the installed plugins of all kinds through one inventory, not three
  per-kind routes (D271); `POST /v1/analyze` runs one plugin as a job and embeds its result in the
  completed job's `analysis_report`; the CLI's `xtalate analyze FILE --plugin <name>` prints the
  namespaced keys (or `--json`); and the Web UI's **Analysis tab** renders results **generically** —
  walking the map by JSON value type with zero branching on any key or plugin name, so a third-party
  plugin renders through the same path as the reference one. A plugin that breaks containment is a
  **reported** failure — a completed job with `analysis_report.status: "error"` naming the plugin — not
  a 500 (D272).
* **The third-party proof and the release (M71).** `tests/fixtures/xtalate_toyanalysis` — a toy
  third-party analysis plugin as its own installable distribution, **written from the developer
  guide's §8 "Writing an analysis plugin" chapter alone**, against only the frozen public SDK, with
  zero core edits — installed as a second analysis CI canary beside the reference plugin. Its suite
  proves the whole contract on a real installed distribution: discovered additively in the registry,
  run and contained by `run_analysis`, absence-honest about a cell-less source's volume (P3/P4), and
  rendered on the CLI consumer surface. Package reaches `1.8.0` on schema `1.0.0`.

## Changed

* **The `main` compose CI rides out transient registry rate limits (D273).** The `main.yml`
  compose-integration and e2e jobs split the single `docker compose up -d --build --wait` into a
  bounded backoff-retry `docker compose pull --ignore-buildable && docker compose build` followed by
  `docker compose up -d --wait` from the now-local images. On both the M69 and M70 merges the compose
  job aborted with `toomanyrequests: Rate exceeded` while a sibling job pulling the identical images
  from a different runner IP passed — proof the throttle is a *transient, per-IP anonymous registry
  rate limit* every public registry enforces, not a config fault a registry-hop cures. This reverses
  the M70 spec's rejection of a retry loop, whose "deterministic infra bug" premise the same-commit
  evidence falsified.

Full Changelog: [v1.7.0...v1.8.0](https://github.com/jsong1218/Xtalate/compare/v1.7.0...v1.8.0)

The chained version sync points (`pyproject.toml`, `__version__`, `CITATION.cff`, the README version
badge, and the regenerated `docs/openapi.json`) read `1.8.0`; `frontend/package.json` is deliberately
not a sync point (untouched at `1.0.0` since the v1.0 flip). Tag and publish remain the maintainer's
manual, nightly-green-gated step (D52).
