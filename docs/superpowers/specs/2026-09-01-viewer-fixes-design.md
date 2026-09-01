# v1.6 UIR-S7 — Mol\* viewer fixes + QoL

**Date:** 2026-09-01
**Branch:** `v1.6-uir-s7-viewer-fixes` (addendum slice to the v1.6 UI redesign)
**Scope:** frontend-only + one deploy Dockerfile line. No engine, schema, or `/v1` change.

## Motivation

Five defects/gaps surfaced from running the shipped v1.6 Structure/Compare viewer:

1. In the Compare tab the two Mol\* windows do not line up — the right (output) one sits lower.
2. Sample ("example") files do nothing on the hosted Render.com demo.
3. Mol\* renders light-themed even when the app is in dark mode.
4. The "Show bonds heuristic" toggle changes nothing on screen.
5. Assorted QoL: no way to recenter a lost camera, no way to enlarge the viewer, and a
   silently-failing sample button.

The guiding rule is unchanged: **never fail silently, never claim a heuristic is file content.**

## Fixes

### F1 — Compare windows line up (subgrid)

**Cause.** `CompareTab` places a self-contained `StructureViewer` in each of two grid columns.
Each viewer stacks a *variable-height* header (label, supplied-lattice badge, legend, no-cell
caption) above a fixed `h-96` canvas. The output side carries the D235 supplied-lattice badge (and
sometimes a no-cell caption) the source side lacks, so its canvas starts lower.

**Fix.** Restructure the `StructureViewer` root as a **3-row CSS grid**:

- row 1 — *annotations* (label, supplied badge, legend, no-cell caption)
- row 2 — *canvas* (the fixed-height Mol\* box + bonds badge overlay)
- row 3 — *controls* (bonds toggle, reset view, expand)

When two viewers are placed by `CompareTab`, the parent grid uses `lg:grid-rows-subgrid`
(Tailwind 3.4.7) with each viewer spanning the three rows, so the annotation/canvas/control rows each
share a height across both columns. Both canvases then align top **and** bottom. The single-viewer
Structure tab is unaffected — subgrid only participates under the compare parent; a lone viewer keeps
its own intrinsic row heights.

`CompareTab`'s existing source-column "Fields the target could not hold" block stays *below* the
viewer's control row (it is compare-specific annotation, not part of the viewer atom), so it does not
perturb canvas alignment.

### F2 — Sample files work on the standalone/Render build

**Cause.** `deploy/demo/Dockerfile` builds the Next.js **standalone** bundle. Next's `output:
"standalone"` does **not** auto-copy `public/`. The Dockerfile comment (line ~79) still claims "the
frontend has no `public/` dir today"; but `public/samples/` was added in S4 (D246). On the hosted
demo `/samples/*` therefore 404s. `SamplePicker.pick` does `if (!res.ok) return`, swallowing the 404
— the buttons appear dead. Local `next dev` (the compose dev stack the e2e suite runs against) serves
`public/`, so the suite never caught it.

**Fix.**
- `deploy/demo/Dockerfile`: `COPY --from=frontend-build /repo/frontend/public ./public` alongside the
  existing `.next/static` copy; correct the stale comment.
- `SamplePicker`: on a failed fetch (or upload), surface an inline, role="alert" error next to the
  picker instead of silently returning (P1 — never fail silently). This is also QoL Q2.

### F3 — Dark mode for Mol\*

**Cause.** The mount never sets a canvas background; Mol\* uses its light default regardless of the
app theme (`data-theme` on `<html>`, owned by `ThemeProvider`).

**Fix.**
- `molstarMount`: add `backgroundColor` to `MountStructureViewerOptions` (applied to the renderer at
  mount) and a `setBackground(color: number)` method on `MountedStructureViewer` that calls
  `plugin.canvas3d.setProps({ renderer: { backgroundColor } })`.
- `StructureViewerMolstar`: read `useTheme()`; pass the theme background at mount and add a
  `useEffect([theme])` that calls `handle.setBackground(...)` live — **no re-mount** (theme is not a
  mount dependency). Colors track the surface token: light `#ffffff`, dark `#0f172a` (the
  `--surface` values in `globals.css`), expressed as Mol\* `Color(0x…)` constants.

### F4 — "Show bonds heuristic" actually draws bonds

**Decision (extends D234).** D234 shipped bonds as a *badge-only* heuristic: atoms-only render, the
toggle only revealed the "Bonds are a display heuristic" badge. That reads as broken. This slice
makes the toggle **draw distance-heuristic bonds** while keeping the honesty guarantees:

- bonds remain **off by default**;
- the "Bonds are a display heuristic, not file content" **badge persists** whenever bonds are shown;
- bonds are **never** claimed as file content and **no report** references them (the loader still
  attaches no bond data — bonds are computed by Mol\*'s distance heuristic at display time only).

This is a genuine policy extension and is recorded as a **new decision (D-next)**; D234's atoms-only
default and no-file-content invariant are preserved.

**Fix.**
- `molstarMount`: add `setBonds(enabled: boolean)` to the handle. When enabled, add a
  `ball-and-stick` bond representation (bond visuals) computed by Mol\*'s built-in distance heuristic
  over the current structure; when disabled, remove it. The atoms-only `spacefill` representation is
  unchanged in both states, so toggling overlays/removes bond sticks without disturbing the atoms or
  the camera. Bonds are re-applied after a window/frame swap if the toggle is on.
- `StructureViewer`: the existing `bondsEnabled` state now drives `handle.setBonds` (threaded through
  `StructureViewerMolstar` as a `bonds` prop) in addition to the badge.

*Implementation note / risk:* Mol\* must compute bonds for a bond-less basic-schema model. If the
built-in `ball-and-stick` heuristic does not auto-compute for this model path, the fallback is to
enable Mol\*'s structure bond computation explicitly; this is verified during implementation before
the toggle is wired to the UI.

### QoL — reset view, expand/fullscreen

Both live in the viewer's row-3 control cluster, beside the bonds toggle.

- **Reset view:** a button calling `PluginCommands.Camera.Reset(plugin)` via a new
  `resetCamera()` handle method — recenters/refits a lost orbit. In the Compare tab, resetting one
  side broadcasts through the existing camera-lock, so both recenter together (no new wiring).
- **Expand:** a button that toggles the viewer container into an enlarged view. MVP: toggle the
  canvas box between `h-96` and a tall near-fullscreen height (`fixed inset-*` overlay with a close
  control and `Escape` to exit), re-fitting the camera on resize. Focus is trapped in the overlay and
  restored on close (a11y parity with the S4 command palette). Mol\* resizes with its container.

## Non-goals

- No per-atom diff / heat-map (that remains v1.8's seam — CompareTab comment).
- No change to the geometry endpoints, canonical model, or reports.
- No bond data in the Canonical Model or any report (bonds stay display-only).

## Testing

- **vitest:** subgrid class assertions on the restructured `StructureViewer`; `setBackground` /
  `setBonds` / `resetCamera` handle methods present and invoked on theme/toggle/reset (the existing
  `StructureViewerMolstar` tests mock the mount handle — extend those mocks); SamplePicker error path
  renders an alert on `!res.ok`.
- **e2e (through Docker, on this branch):** extend `structure-viewer` / `compare-tab` journeys —
  bonds toggle flips a render-level proof (`data-bonds-drawn`), reset-view resets the camera fingerprint
  (`data-camera-*`), dark theme sets a `data-bg` proof, and the two Compare canvases report equal
  top offset. Sample-button e2e already exercises `next dev` (green); the standalone `public/` copy is
  verified by a Docker build check of the demo image (documented in the plan).
- **axe:** the new controls and the expand overlay keep serious+critical at zero (S6 invariant).

## Records

- New decision **D-next**: bonds toggle draws distance-heuristic bonds (extends D234; badge + no-file-content
  invariants preserved).
- MASTER_SPEC revision bump (Part 7 §6) noting the S7 viewer fixes.
- CLAUDE.md status line + memory index updated after merge (maintainer-owned publish/tag unchanged).
