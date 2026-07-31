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
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cb: {
          // Foreground / icon colors, one per §4 meaning.
          preserve: "var(--cb-preserve)",
          "absent-format": "var(--cb-absent-format)",
          "absent-file": "var(--cb-absent-file)",
          removed: "var(--cb-removed)",
          assumption: "var(--cb-assumption)",
          warning: "var(--cb-warning)",
          fail: "var(--cb-fail)",
          skipped: "var(--cb-skipped)",
          // Tinted backgrounds for the panel rows (kept AA against the foregrounds above).
          "preserve-bg": "var(--cb-preserve-bg)",
          "removed-bg": "var(--cb-removed-bg)",
          "assumption-bg": "var(--cb-assumption-bg)",
          "warning-bg": "var(--cb-warning-bg)",
          "fail-bg": "var(--cb-fail-bg)",
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
