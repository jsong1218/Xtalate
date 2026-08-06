# Addendum before M36 — Frontend Redesign (Design Spec)

**Branch:** `frontend-redesign-pre-m36`
**Date:** 2026-08-04
**Status:** Approved design; implementation pending (7 slices).
**Nature:** Enhancement pass, documented as an *Addendum before M36* — not an official milestone.

## 1. Purpose & scope

Make the Web UI (`frontend/`) feel more polished and professional while staying simple,
clean, lightweight, and highly usable for a broad audience — researchers, scientists,
engineers, students, and non-technical users alike.

This is a **UI/UX-only** pass. Explicitly out of scope:

- No changes to the engine (`src/xtalate/`), the `/v1` API (`backend/`), the Canonical
  Model, capability declarations, or any conversion/validation/recovery logic.
- No new scientific behavior, no new formats, no functional workflow changes.

### Binding invariants the redesign must not break

1. **No silent loss (P1).** The report "row completeness / never buried" invariant
   (`ConversionReportPanel` docstring) is presentational-safe only: grouping and collapsing
   are visual conveniences; summary counts stay visible and no individual loss row is hidden
   by default.
2. **Loss palette meaning (Part 7 §4).** The `--cb-*` tokens keep their one-meaning-each
   semantics; color is never the sole carrier of meaning (icon + label always pair with it);
   every foreground/surface pair clears WCAG AA in **both** themes.
3. **Generated read-surfaces stay honest (D103).** The formats explorer remains generated
   from `GET /v1/capabilities`; added editorial prose is additive and degrades gracefully for
   formats it has no entry for (e.g. plugin formats).
4. **Tests are part of the work.** Every `data-testid`, vitest, `globals.contrast.test.ts`,
   and Playwright e2e spec a change touches is updated in the same slice. The full e2e suite
   runs through Docker (per the standing rule) before any commit touching `frontend/`.

## 2. Current state (what exists today)

- **No app shell.** `app/layout.tsx` is a centered `max-w-5xl` container only. Navigation is
  ad-hoc: inline links on the landing page, one-off "Back to home" links on some pages. No
  consistent header, back button, or theme toggle.
- **Light-only, by deliberate design (D96).** `app/globals.css` documents that dark mode was
  *deferred*: the `--cb-*` palette was tuned for a white surface, panels hard-code `bg-white`,
  and `app/globals.contrast.test.ts` guards the light pairs. There is intentionally no
  `prefers-color-scheme` override.
- **`/formats` explorer exists** — a capability grid (`FormatsGrid`) + per-format detail
  (`FormatDetail`), generated from the API. Shows read/write per field; **no editorial prose.**
- **`/docs` site** renders committed `docs/*.md` via `lib/docs/pages.ts`.
- **Reports** (`components/report/`) render flat sections of one-row-per-entry.

## 3. Design language

A calm, professional scientific-tool aesthetic (restraint over decoration): one accent color
for forward actions, a clear type scale, generous whitespace, `rounded-lg` cards with subtle
borders. Only functional transitions (~150ms on hover/expand/theme) — no decorative animation.
Expressed as a small shared design-token vocabulary rather than ad-hoc utility strings.

**Accent color:** a calm professional blue, chosen to work in both themes and to keep the loss
palette's red/amber/violet/green reserved for their meanings. It carries forward/primary
actions only; it is never used for loss semantics.

## 4. Design by area

### 4.1 Theme system (foundation for dark mode) — Slice S1

- **Semantic surface tokens** as CSS variables in `globals.css`, aliased in
  `tailwind.config.ts`: `--surface`, `--surface-raised`, `--border-subtle`, `--text-primary`,
  `--text-muted`, `--accent` (+ `--accent-fg`). Light values match today's look; a
  `:root[data-theme="dark"]` block supplies dark values.
- **Dark, surface-aware `--cb-*` variants.** The current loss foregrounds/backgrounds are
  tuned for white; the dark block supplies lighter foregrounds and dark tinted-row
  backgrounds, each pair holding AA on its dark surface.
- **Tailwind:** `darkMode: "selector"`; alias the new semantic tokens so components write
  `bg-surface` / `text-body` / `border-subtle` instead of `bg-white` / `text-slate-900` /
  `border-slate-200`.
- **ThemeProvider + toggle:** a small client provider; **default light**; the user's explicit
  choice persists to `localStorage`. A tiny inline `<head>` script sets `data-theme` before
  first paint so users who chose dark don't flash light (no-FOUC).
- **Contrast test:** extend `globals.contrast.test.ts` to assert every guarded pair clears AA
  in **both** light and dark.
- **Migration:** replace hard-coded `bg-white` / `text-slate-*` / `border-slate-*` surface
  usages across components with the semantic tokens. Loss tokens stay `--cb-*`.
- **Governance:** `DECISIONS.md` entry overriding D96 (dark mode was deferred; now shipped),
  and an updated rationale comment in `globals.css`.

### 4.2 App shell + back navigation — Slice S2

- A shared shell rendered from `layout.tsx`: **header** with home/logo (left), primary nav
  (Convert · Formats · History · Docs), and the **theme toggle** (right).
- A **consistent back affordance**: a left-arrow control in the upper-left of every
  non-landing page, in the same place everywhere. It navigates by route hierarchy (a
  predictable parent destination), not raw browser-back, so users never feel trapped.
- Retire the ad-hoc inline nav links and one-off "Back to home" links, routing them through
  the shell.

### 4.3 Primary action system — Slice S3

- A shared `Button` primitive with variants: `primary` (large, filled accent, high
  prominence), `secondary` (bordered/subtle), `ghost`/link, and a destructive treatment for
  delete-style actions.
- Forward-moving actions become unmistakably primary: **Upload, Continue, Convert, Download,
  Finish**. Secondary and destructive actions visually recede. Applied consistently across
  upload → inspect → recovery → report → download.

### 4.4 Reports readability — Slice S4

- A **summary band** at the top of the report surface (the existing count chips, elevated to
  an at-a-glance overview).
- Warnings (and, where lengthy, Removed) grouped **by type into collapsible groups that start
  expanded** (accordion, expanded-by-default). Grouping cuts the wall-of-text; expanded-by-
  default keeps the never-buried promise — nothing requires a click to become visible.
- Complements the existing D108 per-frame frame-range collapse; the two together tame
  trajectory-scale floods.
- Preserved / Removed / Supplied & assumptions keep full row fidelity and verbatim engine
  reasons. Update `components/report/*.test.tsx` and the relevant e2e specs.

### 4.5 File Format Guide (enriching `/formats`) — Slice S5

- A typed editorial content module in the frontend (`lib/formats/guide.ts`), keyed by
  `format_id`, with prose fields: what the format is; typical use cases; common software;
  scientific/computational context; advantages; disadvantages; what information it stores
  (structures / trajectories / metadata / forces / energies / cell / velocities); typical
  workflows; important limitations. Written to be understandable by beginners and researchers.
- The per-format detail page (`app/formats/[format_id]/page.tsx` / `FormatDetail`) renders this
  guide **together with** the existing capability grid — one page tells the whole story.
- **Graceful fallback:** a `format_id` with no guide entry (e.g. a plugin format) still shows
  the capability grid, with an honest note that no extended guide exists for it. The formats
  index may surface a short blurb per format where an entry exists.

### 4.6 Accessibility & UX sweep — Slice S6

- `focus-visible` rings on all interactive elements; keyboard operability for the new shell,
  theme toggle, and accordions.
- Contrast audited in both themes; responsive checks at mobile/tablet breakpoints; consistent
  spacing and type scale; clearer inline error copy where it is currently thin.
- No functional change. Closes with a full Docker-based e2e run on this branch.

### 4.7 Documentation & addendum — Slice S7

- `CHANGELOG.md`: an "Addendum before M36" entry summarizing the UI/UX pass.
- `DECISIONS.md`: entries for (a) dark mode shipped, overriding D96; (b) accordion-vs-never-
  buried reconciliation (expanded-by-default grouping); (c) format guide as additive editorial
  content on generated read-surfaces.
- A short addendum note in the private plan docs. The record ships with the code (v0.7
  standing rule).

## 5. Slice plan

Each slice is independently reviewable and shippable. S1 is the foundation everything builds
on; S2–S5 are otherwise largely independent; S6–S7 close out. The user may direct that two
slices be implemented together.

| # | Slice | Primary deliverables |
|---|-------|----------------------|
| **S1** | Theme foundation | Semantic + dark `--cb-*` tokens, Tailwind aliases, ThemeProvider/toggle/no-FOUC, contrast test (both themes), component surface migration, D96-override note. |
| **S2** | App shell + back nav | Shared header, theme-toggle mount, consistent back button, retire ad-hoc links. |
| **S3** | Primary action system | `Button` primitive + variants; apply across upload/convert/recovery/download/finish. |
| **S4** | Reports readability | Summary band + grouped expandable warnings (expanded default); update report tests + e2e. |
| **S5** | Format guide | Editorial content module + enriched `/formats/[format_id]`; graceful plugin fallback. |
| **S6** | A11y & UX polish + verification | Focus/keyboard/contrast/responsive/error-copy sweep; full Docker e2e run. |
| **S7** | Documentation & addendum | CHANGELOG, DECISIONS, plan-doc addendum note. |

## 6. Risks & mitigations

- **Test churn from restyling.** Many vitest/e2e specs key on `data-testid` and text. Keep
  test ids stable; update assertions in the same slice; run the full Docker e2e suite before
  committing frontend changes.
- **Dark-mode contrast regressions.** The extended contrast test is the guard; a token edit
  that drops any pair below AA in either theme fails CI.
- **Never-buried tension with accordions.** Mitigated by design: expanded-by-default groups and
  always-visible summary counts; no loss row is hidden behind a click by default.
- **Scope creep toward Secondary Goals.** No viewing/editing/analysis features; this pass only
  restyles and reorganizes existing surfaces.
