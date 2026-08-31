import typography from "@tailwindcss/typography";
import type { Config } from "tailwindcss";

/**
 * Tailwind config.
 *
 * The loss-communication palette (MASTER_SPEC Part 7 §4) is defined **once** as `--cb-*` CSS
 * custom properties in `app/globals.css` (D90/token-once rule). Here we only *alias* those
 * variables into Tailwind's color scale so components can write `text-cb-removed` /
 * `bg-cb-assumption-bg` instead of repeating hex — the single source of truth stays the CSS
 * variable, and dark-mode / accessibility tuning happens in one place. Never hard-code a loss
 * color anywhere else.
 */
const config: Config = {
  // Dark mode is selector-driven: the `data-theme="dark"` attribute on <html> (set by the
  // ThemeProvider, default light) toggles the whole palette. Not `prefers-color-scheme` — the theme
  // is an explicit, persisted user choice (see globals.css, which overrides D96).
  darkMode: ["selector", ':root[data-theme="dark"]'],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Monospace for every value, count, and identifier (UI redesign S1, D243). System stack
        // only — no web font (keeps the self-host lean and the CSP simple). Components write
        // `font-mono`; the DataValue primitive applies it to scientific readouts.
        mono: [
          "ui-monospace",
          "SF Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        // Semantic surface chrome — the neutral tokens every page is built from (globals.css).
        // Components write `bg-surface` / `text-body` / `border-line` instead of `bg-white` /
        // `text-slate-900`, so one theme flip re-skins the app. Single source of truth is the CSS var.
        //
        // NB: Tailwind shares a color key across bg-/text-/border-, so the keys are chosen to be
        // collision-free per role: text uses strong/body/muted/faint, backgrounds surface/raised/well,
        // borders line/line-soft/line-strong. (The CSS var it points at keeps its role-descriptive
        // name, e.g. the `strong` key → `--text-strong`.)
        surface: "var(--surface)", // bg-surface   ← page/panel (was bg-white)
        raised: "var(--surface-raised)", // bg-raised    ← subtle raised/hover (was bg-slate-50)
        well: "var(--surface-muted)", // bg-well      ← inert chip fill (was bg-slate-100/200)
        line: "var(--border-default)", // border-line  ← default hairline (was border-slate-200/300)
        "line-soft": "var(--border-subtle)", // border-line-soft ← faint divider (was slate-100)
        "line-strong": "var(--border-strong)", // border-line-strong ← selected outline (was slate-900)
        strong: "var(--text-strong)", // text-strong  ← headings (was text-slate-900/800)
        body: "var(--text-body)", // text-body    ← paragraph (was text-slate-700)
        muted: "var(--text-muted)", // text-muted   ← secondary (was text-slate-600)
        faint: "var(--text-faint)", // text-faint   ← hints/meta (was text-slate-500/400)
        inverse: "var(--inverse)", // bg-inverse   ← neutral filled button (was bg-slate-900)
        "inverse-fg": "var(--inverse-fg)", // text-inverse-fg ← text on it (was text-white there)
        "inverse-hover": "var(--inverse-hover)", // hover:bg-inverse-hover (was hover:bg-slate-700)
        accent: "var(--accent)", // bg-accent    ← forward-action accent (S3)
        "accent-fg": "var(--accent-fg)",
        "accent-hover": "var(--accent-hover)",
        // The accent used as text — links, the active-tab label (UI redesign S1, D243). A separate
        // token from the fill because teal-as-text on the dark surface needs a lighter tone
        // (`--accent-text` in globals.css) than the button fill can give.
        "accent-text": "var(--accent-text)", // text-accent-text ← links / active tab
        cb: {
          // Foreground / icon colors, one per §4 meaning.
          preserve: "var(--cb-preserve)",
          "absent-format": "var(--cb-absent-format)",
          "absent-file": "var(--cb-absent-file)",
          removed: "var(--cb-removed)",
          assumption: "var(--cb-assumption)",
          warning: "var(--cb-warning)",
          fail: "var(--cb-fail)",
          "fail-solid": "var(--cb-fail-solid)",
          skipped: "var(--cb-skipped)",
          // Tinted backgrounds for the panel rows (kept AA against the foregrounds above).
          "preserve-bg": "var(--cb-preserve-bg)",
          "removed-bg": "var(--cb-removed-bg)",
          "assumption-bg": "var(--cb-assumption-bg)",
          "warning-bg": "var(--cb-warning-bg)",
          "fail-bg": "var(--cb-fail-bg)",
          // The viewer's bonds-heuristic badge (M63-S2, D241): amber notice, distinct from the §4
          // palette; both values are AA-guarded tokens in globals.css (never a hard-coded hue).
          "bonds-bg": "var(--bonds-bg)",
          "bonds-fg": "var(--bonds-fg)",
        },
      },
    },
  },
  // The docs site (M34-S1) renders the committed `docs/` Markdown corpus; the typography plugin's
  // `prose` classes style headings, tables, and code blocks without hand-classing each element. Loss
  // colors stay the `--cb-*` variables above — typography only touches long-form doc prose.
  plugins: [typography],
};

export default config;
