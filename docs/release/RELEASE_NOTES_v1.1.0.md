# Xtalate v1.1.0 — Release Notes

> **Status: draft.** Prepared at the M41 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.1.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.1.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release ships **no schema change** — so the mandatory `Schema version:` line above reads `1.0.0`,
not `1.1.0`. A schema number that incremented without a schema change would be a version that lies;
the honest statement is a package bump on a frozen schema.

## What's new in 1.1.0

- **The `ambiguous_stress_convention` recovery scenario (M40).** extXYZ stress is no longer an
  opaque carry: a carried stress tensor's sign convention is resolved **only** under an explicit,
  recorded choice — `ase_sign_convention` / `tension_positive` — and an undeclared convention
  refuses (`RECOVERY_REQUIRED`), never interpreted (a sign flip is invisible in the output). On the
  CLI: `--recover ambiguous_stress_convention=tension_positive`.
- **extXYZ `electronic.stress` promoted to PARTIAL on read and write (M40).** A resolved stress is
  written back to extXYZ reversed to the compression-positive convention its ASE-native files carry,
  reported as a `STRESS_SIGN_CONVENTION_CHANGED` Conversion Report warning; an unresolved carry still
  round-trips verbatim (no regression).
- **The MLIP interchange proof (M41).** A governed golden case
  (`tests/golden/extxyz/mlip-labeled-2frame/`, licensed manifest under the corpus rules) proves
  labeled extXYZ round-trips per-frame `energy`, per-atom `forces`, and `stress` **all first-class**
  under the scenario preset — the roadmap's "speaks the MLIP training lingua franca completely"
  stopping point — with the materialized and streamed no-preset refusals asserted
  report-identical. The nightly matrix and the report-completeness property test admit the case with
  zero suite edits; the other five formats show no regression.
- **Also in this release (M39):** a public hosted demo (single-container, ephemeral, anonymous),
  Web UI fixes (dark-mode form controls, a confirm-before-convert step, a completion
  chime/notification), and a CLI terminal-bell completion signal.

## What stays deferred

- **`virial`** — the virial↔stress volume-scaling option — is named but unbuilt and tracks to
  **v1.1.1**: it needs the cell volume for the volume-scaling relation, so it is absent from the
  offered list until then (naming it refuses; never offered-then-refused).
- **Web UI per-scenario copy** tracks to **v2.0** — new scenarios render through the generic option
  list and the shared loss vocabulary until then: functional and honest, no frontend change.

## Install

```bash
pip install xtalate                # the library + the `xtalate` CLI
pip install "xtalate[service]"     # + the FastAPI /v1 service layer
```

**Additive-minor release.** Everything a 1.0 consumer built against — the frozen schema, the Plugin
SDK, the `/v1` contract, the documented CLI flags — keeps working unchanged: the reference-plugin
compatibility canary runs green in CI as the proof, and no engine-below-schema, `/v1`, CLI, or
frontend contract changed. Existing conversion records and files written by 1.0 remain valid
(`tool_version` stamps now read `1.1.0`; `schema_version` stays `1.0.0`).
