# Xtalate v1.7.1 — Release Notes

> **Status: draft.** Prepared for the maintainer to attach to the GitHub release at tag time (D52).
> Nothing here is published until the maintainer tags and releases — `git tag v1.7.1` and the
> PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.7.1` · schema `1.0.0`.** This is the **shipped** File Repair line: v1.7.0 was staged
as the M67 release close but superseded before publication, so v1.7.1 contains all of M64–M67
(the closed set of four repair operations, the CLI/API/UI surfaces, the property suite) **plus**
the in-place repair recovery and wrap hardenings below. The canonical `schema_version` is
unchanged at `1.0.0` — still no shape change: repairs ride reserved `operation="repair"`
vocabulary, and nothing here adds a field.

## What's new in 1.7.1

- **A resumed blocked repair completes in place (D260).** The one honest limitation the 1.7.0
  notes named — a cell-less `wrap_into_cell` over HTTP re-pausing on every resume even after the
  recovery question was answered — is resolved. The resume (and the CLI's
  `--recover missing_lattice=…` preset) applies the pre-supplied recovery choice to the object
  **before** the blocked repair is retried: the cell is fabricated by the caller's own choice,
  the wrap runs against it, and the conversion completes. The choice is recorded as an ordinary
  recovery Assumption — ahead of the repair row it enabled, in application order — and a lattice
  fabricated only for a target that cannot store it (a wrap on plain XYZ) is audited in
  `supplied` without entering the write plan (D47). All-or-nothing is preserved: a repair that
  still blocks after a supplied recovery refuses with the pre-repair Assumptions carried.
- **The wrap fold is idempotent at every precision (D258→D260).** The M67 property suite found
  that a coordinate within float-underflow of a cell face (a fractional residue below the ULP of
  1.0, ~1.1e-16) folded onto the face on the first wrap and to `0.0` on the next. The fold now
  clamps `1.0 → 0.0`, keeping every fold inside `[0, 1)` — deterministic as before, and
  idempotent everywhere. The property suite asserts the full domain now.
- **The R5 warning is conditional.** `WRAP_DISCARDS_UNWRAPPED_PATHS` fires only when the
  application actually moved positions (beyond the 1e-9 Å position tolerance); an already-in-cell
  structure discards no trajectory information, so the no-op wrap carries no warning — the
  deduplicate/species-reorder no-op discipline.

## Migration notes

None. Schema `1.0.0`, wire additive-only, `operation="repair"` already active — a client written
against 1.7.0 needs no change (the resume that used to re-pause now completes, which is the
fix). A CLI invocation that previously refused with exit 2 — cell-less wrap plus a
`--recover missing_lattice=…` preset — now completes with exit 0.