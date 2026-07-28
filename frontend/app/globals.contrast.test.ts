import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The automated WCAG AA contrast guard for the loss palette (MASTER_SPEC Part 7 §4; M30-S2). The
 * M30 accessibility pass computed these ratios once by hand and fixed what failed (`--cb-fail`
 * darkened to clear AA on its own tint; the harmful dark-mode override removed — D96). This test
 * makes that permanent: it reads the *actual* token values from `globals.css` and fails CI if any
 * pair a component really renders drops below 4.5:1, so a future palette edit cannot silently
 * reintroduce an illegible combination.
 *
 * The pairs mirror how the tokens are used: each foreground as text/icon on the white page, each
 * foreground as text on its own tint (report-row badges and links), and the body text colors on
 * every tint (the panel surfaces). White-on-fail is the one filled badge (the ✕ glyph).
 */

// Vitest runs from the frontend package root, so resolve the stylesheet from there (jsdom's
// `import.meta.url` is not a file:// URL). The token values under test are read from this file.
const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

/** Pull a `--cb-*: #rrggbb;` declaration out of the stylesheet — the single source of truth. */
function token(name: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  if (!match) throw new Error(`token --${name} not found in globals.css`);
  return match[1];
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
/** WCAG 2.x relative-contrast ratio between two colors. */
function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const AA = 4.5; // normal-size text / meaningful icons
const WHITE = "#ffffff";
const SLATE_900 = "#0f172a";
const SLATE_700 = "#334155"; // the secondary body color used on tinted panels

const FOREGROUNDS = [
  "cb-preserve",
  "cb-absent-format",
  "cb-absent-file",
  "cb-removed",
  "cb-assumption",
  "cb-warning",
  "cb-fail",
  "cb-skipped",
];
const TINTS = ["cb-preserve-bg", "cb-removed-bg", "cb-assumption-bg", "cb-warning-bg", "cb-fail-bg"];
/** Foreground token → the tint it is rendered as text upon (report-row badges/links). */
const FG_ON_TINT: [string, string][] = [
  ["cb-preserve", "cb-preserve-bg"],
  ["cb-removed", "cb-removed-bg"],
  ["cb-assumption", "cb-assumption-bg"],
  ["cb-warning", "cb-warning-bg"],
  ["cb-fail", "cb-fail-bg"],
];

describe("loss palette — WCAG AA contrast", () => {
  it.each(FOREGROUNDS)("%s clears AA as text on the white page", (name) => {
    expect(contrast(token(name), WHITE)).toBeGreaterThanOrEqual(AA);
  });

  it.each(FG_ON_TINT)("%s clears AA as text on its own tint %s", (fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(AA);
  });

  it.each(TINTS)("body text (slate-900 and slate-700) clears AA on %s", (bg) => {
    expect(contrast(SLATE_900, token(bg))).toBeGreaterThanOrEqual(AA);
    expect(contrast(SLATE_700, token(bg))).toBeGreaterThanOrEqual(AA);
  });

  it("white text on the filled fail badge clears AA", () => {
    expect(contrast(WHITE, token("cb-fail"))).toBeGreaterThanOrEqual(AA);
  });

  it("carries no prefers-color-scheme:dark override (the v0.6 UI is light-surface only, D96)", () => {
    // A dark override that lightened the foregrounds while the panels stayed `bg-white` would drop
    // contrast, not raise it — so its absence is part of the accessibility contract, not an omission.
    expect(css).not.toMatch(/prefers-color-scheme:\s*dark/);
  });
});
