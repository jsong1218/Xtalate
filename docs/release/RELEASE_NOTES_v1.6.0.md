# Xtalate v1.6.0 — Release Notes

> **Status: draft.** Prepared at the M63 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.6.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.6.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release is **API-additive + frontend** — read-only geometry endpoints and a Mol\* viewer, adding
**zero fields** to the Canonical Object — so the mandatory `Schema version:` line above reads
`1.0.0`, not `1.6.0`. A viewer that reads the schema does not change it, and a schema number that
incremented without a schema change would be a version that lies; the honest statement is a package
bump on a frozen schema. The library and CLI surface is untouched — `xtalate capabilities` lists
exactly what v1.5 listed.

## What's new in 1.6.0

- **See what the report says.** v1.6 adds a read-only visualization layer over the workflow: a
  Mol\*-based viewer that renders **the structure the report describes**, fed straight from the
  Canonical Object. It is a viewer, never an editor — measurement, selection, and rendering export
  are deliberate omissions (roadmap §2 secondary-goal scope, P6). Every fact the canvas shows also
  exists as text in a report, and the reports remain the record: **the reports are the accessible
  record; the viewer is an additional presentation** (D241).
- **Read-only canonical-geometry endpoints (M59).** Two additive `GET` routes expose an uploaded
  file's — or a conversion's source/output — canonical geometry as JSON:
  `GET /v1/files/{file_id}/geometry` and
  `GET /v1/conversions/{conversion_id}/geometry?side=source|output`. Both take a half-open, 0-based
  `?frames=start:end` window (default `0:1`, a single structure) and return `species`, an optional
  per-frame `cell`, and per-frame `positions`. They ride the existing streaming engine — never
  materializing a whole trajectory — behind a byte-bounded server-side cache, so server memory
  stays bounded by the window plus the cache budget. Two honesty rules are pinned: **absence renders
  as absence** — a cell-less source answers `cell: null`, never a fabricated box, and the projection
  carries no bonds (P3); and **geometry expires with the bytes** — `410 FILE_EXPIRED` /
  `OUTPUT_EXPIRED` once the underlying bytes are gone, while the conversion record and its reports
  stay readable. A malformed or reversed range is `400 INVALID_FRAME_RANGE` (D232).
- **The Structure tab (M60).** The **Structure** tab on `/files/[file_id]` and
  `/conversions/[conversion_id]` renders the M59 viewer with a species legend (color paired with the
  element label as text), the unit-cell wireframe drawn **only when a cell is present** — a cell-less
  file renders boxless with the explicit no-simulation-cell caption (P3) — and the ◆ supplied-violet
  rule: a lattice fabricated by recovery renders violet with its Assumption one click away (the
  flagship, `relax.traj → POSCAR`'s bounding box). Honest loading / expired / refused states
  throughout — expired bytes read the expired copy with the reports intact; a refused conversion
  mounts no viewer (D235).
- **Trajectory animation (M61).** Multi-frame objects gain a **frame scrubber + playback**: a
  client-side sliding window over the ranged endpoint keeps decoded frames memory-bounded — browser
  memory stays flat under sustained playback, never the whole trajectory — the readout is a **frame
  number** (`frame N / M`) with **no invented time axis** (the wire carries no timestep), and each
  displayed frame draws **that frame's** unit cell (a variable-cell NpT trajectory breathes; a
  cell-less frame draws no box). Frame indices are the report's own; a `frame_selection` conversion
  names its source frame from the report's Assumption, one click away. Large trajectories degrade
  honestly — the scrubber states that windows re-stream from the server, never a hidden stall
  (D236–D238).
- **The Compare tab (M62).** The **Compare** tab on `/conversions/[conversion_id]` renders the two
  objects the Validation Engine diffed — source and re-parsed output — side by side in two
  synchronized viewers (camera-locked always, frame-locked only where the frame counts match, with
  the exported-frame marker on the source track). Every annotation is **report-sourced, never a
  client computation**: the RMSD overlay reads the Validation Report's own `positions_rmsd` measured
  value (the sole quantitative number on the tab, check row one click away), dropped-field reasons
  render the Conversion Report's `removed` entries verbatim on the source side, and the
  supplied-violet correlation marks a fabricated lattice on the output side only. A one-side-expired
  Compare names the expired side and renders no viewer; a refused conversion's page is its refusal
  (D239–D240).
- **Accessibility posture, e2e/perf hardening, the release (M63).** The viewer is a `<canvas>` and
  is not the accessible record — and does not need to be, because every fact it presents exists as
  text in a report. What meets the WCAG AA bar is the viewer **chrome** — legend, captions,
  scrubber, badges, Compare overlays — contrast-guarded in both themes and keyboard-traversable (tab
  switch + arrow scrub + reachable controls), swept by axe over the live Structure and Compare tabs
  (serious+critical, zero violations). The implementation-plan §5 browser suite is closed as
  asserted e2e journeys (cell-less boxless caption, an NpT cell animating, a timestep-less XDATCAR
  scrubbing by frame number, geometry 410s with the reports intact, the Compare flagship, bonds off
  by default with the persistent heuristic badge and no report mentioning them, D234). The M59/M61
  spike numbers were re-measured on the finished tabs and recorded as release artifacts — **measured,
  not gated** — with no regression: browser playback holds flat at 55→57 MiB, and high-atom
  geometry scrub re-streams at ~2.6 s/window (D241).

The chained version sync points (`pyproject.toml`, `__version__`, `CITATION.cff`, the regenerated
`docs/openapi.json`) read `1.6.0`; `frontend/package.json` is deliberately not a sync point
(untouched at `1.0.0` since the v1.0 flip, v1.5/M58 precedent). Tag and publish remain the
maintainer's manual, nightly-green-gated step (D52).
