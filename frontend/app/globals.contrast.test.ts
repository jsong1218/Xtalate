import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The automated WCAG AA contrast guard for the UI palette (MASTER_SPEC Part 7 §4; M30-S2, extended
 * by the pre-M36 frontend-redesign addendum). The M30 accessibility pass computed the loss-palette
 * ratios once by hand and fixed what failed. This test makes that permanent: it reads the *actual*
 * token values from `globals.css` and fails CI if any pair a component really renders drops below
 * 4.5:1, so a future palette edit cannot silently reintroduce an illegible combination.
 *
 * **Two themes now (the addendum).** The redesign ships a real dark theme selected by
 * `:root[data-theme="dark"]` (default light, opt-in toggle). So every pair is checked in *both*
 * themes: the light values live in the base `:root {…}` block and the dark values in the
 * `:root[data-theme="dark"] {…}` block. The two are parsed separately so a token that is legible in
 * light but not in dark (or vice-versa) fails CI. This replaces the old "carries no
 * prefers-color-scheme override" assertion, which encoded the now-retired light-surface-only rule
 * (D96, overridden by the addendum): dark mode arrives as `data-theme`, not `prefers-color-scheme`.
 *
 * The pairs mirror how the tokens are used: each loss foreground as text/icon on the page surface,
 * each loss foreground as text on its own tint (report-row badges and links), the body text colors
 * on every tint, white-on-fail (the one filled ✕ badge), and the semantic surface tokens
 * (text-on-surface, inverse-fg-on-inverse) the app chrome is built from.
 */

// Vitest runs from the frontend package root, so resolve the stylesheet from there (jsdom's
// `import.meta.url` is not a file:// URL). The token values under test are read from this file.
// Strip CSS comments first: the file's doc comment contains the literal prose ":root {…}", which the
// block regexes below would otherwise match instead of the real declaration blocks.
const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

/** The `:root { … }` base block (light theme). */
function lightBlock(): string {
  const match = /:root\s*\{([\s\S]*?)\}/.exec(css);
  if (!match) throw new Error("base :root block not found in globals.css");
  return match[1];
}
/** The `:root[data-theme="dark"] { … }` override block. */
function darkBlock(): string {
  const match = /:root\[data-theme="dark"\]\s*\{([\s\S]*?)\}/.exec(css);
  if (!match) throw new Error(':root[data-theme="dark"] block not found in globals.css');
  return match[1];
}

/** Pull a `--name: #rrggbb;` declaration out of one theme block — the single source of truth. */
function token(block: string, name: string, theme: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  if (!match) throw new Error(`token --${name} not found in the ${theme} block of globals.css`);
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
/** Foreground token → the tint it is rendered as text upon (report-row badges/links). */
const FG_ON_TINT: [string, string][] = [
  ["cb-preserve", "cb-preserve-bg"],
  ["cb-removed", "cb-removed-bg"],
  ["cb-assumption", "cb-assumption-bg"],
  ["cb-warning", "cb-warning-bg"],
  ["cb-fail", "cb-fail-bg"],
];
const TINTS = ["cb-preserve-bg", "cb-removed-bg", "cb-assumption-bg", "cb-warning-bg", "cb-fail-bg"];

/** Run the whole battery against one theme block. */
function checkTheme(theme: string, block: () => string) {
  describe(`${theme} theme`, () => {
    const t = (name: string) => token(block(), name, theme);

    it.each(FOREGROUNDS)("%s clears AA as text on the page surface", (name) => {
      expect(contrast(t(name), t("surface"))).toBeGreaterThanOrEqual(AA);
    });

    it.each(FG_ON_TINT)("%s clears AA as text on its own tint %s", (fg, bg) => {
      expect(contrast(t(fg), t(bg))).toBeGreaterThanOrEqual(AA);
    });

    it.each(TINTS)("body text (text-strong and text-body) clears AA on %s", (bg) => {
      expect(contrast(t("text-strong"), t(bg))).toBeGreaterThanOrEqual(AA);
      expect(contrast(t("text-body"), t(bg))).toBeGreaterThanOrEqual(AA);
    });

    it("white text on the filled fail badge (cb-fail-solid) clears AA", () => {
      expect(contrast(WHITE, t("cb-fail-solid"))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["text-strong", "text-body", "text-muted", "text-faint"])(
      "%s clears AA on the page surface",
      (name) => {
        expect(contrast(t(name), t("surface"))).toBeGreaterThanOrEqual(AA);
      },
    );

    it("inverse foreground clears AA on the inverse surface (neutral buttons)", () => {
      expect(contrast(t("inverse-fg"), t("inverse"))).toBeGreaterThanOrEqual(AA);
    });

    // The forward-action accent is a rendered surface as of the addendum S3 Button primitive: the
    // filled primary button is `--accent-fg` on `--accent`. Guard that pair so a future accent edit
    // (e.g. brightening the dark blue) cannot silently drop the label below AA in either theme.
    it("accent foreground clears AA on the accent surface (primary buttons)", () => {
      expect(contrast(t("accent-fg"), t("accent"))).toBeGreaterThanOrEqual(AA);
    });
  });
}

describe("UI palette — WCAG AA contrast", () => {
  checkTheme("light", lightBlock);
  checkTheme("dark", darkBlock);
});
