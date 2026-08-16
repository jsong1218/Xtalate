# Xtalate v1.2.0 — Release Notes

> **Status: draft.** Prepared at the M45 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.2.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.2.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release ships **no schema change** — so the mandatory `Schema version:` line above reads `1.0.0`,
not `1.2.0`. A schema number that incremented without a schema change would be a version that lies;
the honest statement is a package bump on a frozen schema.

## What's new in 1.2.0

- **Two read-only VASP-output formats — `vasprun.xml` and `OUTCAR` — with the parser-only concept
  made first-class (M42–M43).** A DFT code's output is a conversion *source*, never a *target*: both
  formats register a parser with **no** exporter, so they appear read-only in `xtalate capabilities`
  and there is no `convert --to vasprun` (or `--to outcar`). Both are streaming-first and read
  **label-complete** through a shared mapping core — per-frame energy, per-atom forces, first-class
  tension-positive stress (mapped deterministically from VASP's declared kBar/compression-positive
  convention), per-step cells — and an unrecognized or inconsistent layout is **refused**, never
  partial-parsed. OUTCAR adds version-drift resilience (both 5.x and 6.x layouts) and torn-tail
  recovery for a killed job.
- **The flagship MLIP conversion, proven end to end and at 10⁴ scale (M44).** `xtalate convert
  OUTCAR --to extxyz` (equally `vasprun.xml --to extxyz`) produces a label-complete training file —
  energy, forces, and stress all first-class — streamed at a small fraction of the materialized
  memory footprint with byte-identical output, and re-validated by the automatic Validation Report.
  The duplicate-source policy is enforced: Xtalate converts the **one** file it is given and never
  cross-reads a sibling OUTCAR/vasprun.xml.
- **First-class magnetic moments from OUTCAR (M45).** A spin-polarized run's per-ion moments map to
  `electronic.magnetic_moments` (μB, spin-up-positive) — closing a gap in which the `magnetization
  (x)` table was silently skipped. vasprun.xml carries no per-ion magnetization block, so a
  spin-polarized vasprun legitimately leaves the field `None`; the two readers' cross-check asserts
  that honest asymmetry, never a fake agreement.
- **VASP real-world hardening as a hybrid corpus (M45).** The real-world test corpus now admits the
  two read-only formats under an OUTCAR↔vasprun **pair-agreement** oracle, exercised by an
  authored-realistic batch spanning single-point, relaxation, NpT MD, spin-polarized,
  killed-truncated and layout-drift runs across VASP 5.x and 6.x. Batch 1 is self-authored
  (Apache-2.0); **real community-contributed OUTCAR/vasprun pairs are welcome** into the same
  harness — see the *Contributing real-world VASP files* section of the developer guide.

## What stays deferred

- **`virial`** — the virial↔stress volume-scaling option — remains named but unbuilt, tracked to
  **v1.1.1**: it needs the cell volume for the volume-scaling relation, so it is absent from the
  offered list until then (naming it refuses; never offered-then-refused).
- **Non-collinear magnetization** tracks to **v1.2.1** — the OUTCAR `(x)/(y)/(z)` SOC tables are a
  moment *vector* per ion, carried verbatim with a named warning until a canonical vector shape
  exists; the collinear scalar moments above are first-class now.
- **Web UI per-scenario copy** tracks to **v2.0** — new scenarios render through the generic option
  list and the shared loss vocabulary until then: functional and honest, no frontend change.
- **Real-world corpus contributions** are ongoing — the harness is permanent; the standing call
  invites community files as they arrive.

## Install

```bash
pip install xtalate                # the library + the `xtalate` CLI
pip install "xtalate[service]"     # + the FastAPI /v1 service layer
```

**Additive-minor release.** Everything a 1.1 consumer built against — the frozen schema, the Plugin
SDK, the `/v1` contract, the documented CLI flags — keeps working unchanged: the reference-plugin
compatibility canary runs green in CI as the proof, and no engine-below-schema, `/v1`, CLI, or
frontend contract changed. Existing conversion records and files written by 1.1 remain valid
(`tool_version` stamps now read `1.2.0`; `schema_version` stays `1.0.0`).
