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
const css = readFileSync(
  resolve(process.cwd(), "app/globals.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

/** The base block, shared by the light theme and the paper surface: `:root, [data-surface="paper"] { … }`. */
function lightBlock(): string {
  const match = /:root\s*,\s*\[data-surface="paper"\]\s*\{([\s\S]*?)\}/.exec(css);
  if (!match)
    throw new Error(
      '`:root, [data-surface="paper"]` base block not found in globals.css',
    );
  return match[1];
}
/** The `:root[data-theme="dark"] { … }` override block. */
function darkBlock(): string {
  const match = /:root\[data-theme="dark"\]\s*\{([\s\S]*?)\}/.exec(css);
  if (!match)
    throw new Error(':root[data-theme="dark"] block not found in globals.css');
  return match[1];
}

/** Pull a `--name: #rrggbb;` declaration out of one theme block — the single source of truth. */
function token(block: string, name: string, theme: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  if (!match)
    throw new Error(
      `token --${name} not found in the ${theme} block of globals.css`,
    );
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
const FOCUS = 3.0; // WCAG 1.4.11 non-text contrast: focus indicators vs adjacent colors
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
  // ⟳ "Modified on request" (v1.7 M66-S3, D257): the repair foreground must clear the same AA bar
  // as every other §4 token — #1d4ed8 on white ≈ 6.7:1 light, #60a5fa on slate-900 ≈ 7.0:1 dark.
  "cb-repair",
];
/** Foreground token → the tint it is rendered as text upon (report-row badges/links). */
const FG_ON_TINT: [string, string][] = [
  ["cb-preserve", "cb-preserve-bg"],
  ["cb-removed", "cb-removed-bg"],
  ["cb-assumption", "cb-assumption-bg"],
  ["cb-warning", "cb-warning-bg"],
  ["cb-fail", "cb-fail-bg"],
  ["cb-repair", "cb-repair-bg"],
];
const TINTS = [
  "cb-preserve-bg",
  "cb-removed-bg",
  "cb-assumption-bg",
  "cb-warning-bg",
  "cb-fail-bg",
  "cb-repair-bg",
];

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

    it.each(TINTS)(
      "body text (text-strong and text-body) clears AA on %s",
      (bg) => {
        expect(contrast(t("text-strong"), t(bg))).toBeGreaterThanOrEqual(AA);
        expect(contrast(t("text-body"), t(bg))).toBeGreaterThanOrEqual(AA);
      },
    );

    it("white text on the filled fail badge (cb-fail-solid) clears AA", () => {
      expect(contrast(WHITE, t("cb-fail-solid"))).toBeGreaterThanOrEqual(AA);
    });

    it.each(["text-strong", "text-body", "text-muted", "text-faint"])(
      "%s clears AA on the page surface",
      (name) => {
        expect(contrast(t(name), t("surface"))).toBeGreaterThanOrEqual(AA);
      },
    );

    // `text-faint` also renders on the *raised* panel surface, a step lighter than the page
    // `--surface`: the report-group count badges ("(1)/(2)") and every provenance `dt` label sit on
    // `bg-raised`. The v2.0 addendums Steel retune (Task 6) left the dark faint one hundredth short
    // there — 4.49:1 — which the whole-page axe scan caught (`e2e/accessibility.spec.ts`) after this
    // isolated guard, then checking faint only on `--surface`, had passed. Pin the exact pair so a
    // future faint edit cannot silently drop the report/provenance metadata below AA again.
    it("text-faint clears AA on the raised panel surface (report groups, provenance)", () => {
      expect(
        contrast(t("text-faint"), t("surface-raised")),
      ).toBeGreaterThanOrEqual(AA);
    });

    it("inverse foreground clears AA on the inverse surface (neutral buttons)", () => {
      expect(contrast(t("inverse-fg"), t("inverse"))).toBeGreaterThanOrEqual(
        AA,
      );
    });

    // The forward-action accent is a rendered surface as of the addendum S3 Button primitive: the
    // filled primary button is `--accent-fg` on `--accent`. Guard that pair so a future accent edit
    // (e.g. brightening the dark blue) cannot silently drop the label below AA in either theme.
    it("accent foreground clears AA on the accent surface (primary buttons)", () => {
      expect(contrast(t("accent-fg"), t("accent"))).toBeGreaterThanOrEqual(AA);
    });

    // The forward-action accent is also rendered as *text* — links and the active-tab label — on
    // the page surface (UI redesign S1, D243). Teal-as-text on the dark surface needs a lighter
    // tone than the button-fill teal (which only reaches ~3.3:1 on slate-900), so the two are
    // separate tokens: `--accent-text` vs `--accent`. Guard the pair in both themes.
    it("accent text clears AA on the page surface (links, active tab)", () => {
      expect(contrast(t("accent-text"), t("surface"))).toBeGreaterThanOrEqual(
        AA,
      );
    });

    // The viewer chrome pairs (v1.6 M63-S2, D241): the Structure/Compare tab chrome must meet the
    // WCAG AA bar of the v0.6 pass — the canvas is not the accessible record, but the chrome is.
    // The ◆ supplied-violet annotation and the exported-frame marker reuse the already-guarded §4
    // loss tokens (`cb-assumption` on `cb-assumption-bg`, `cb-assumption` on `surface` — guarded
    // above), so only the viewer's own non-loss pairs are listed here. The legend rows, the
    // cell-less caption, and the Compare RMSD caption are `text-muted`/`text-body` on the same
    // surfaces, asserted here at the exact chrome combination.
    it.each([
      ["bonds-fg", "bonds-bg"], // the bonds-heuristic badge (its text on its own fill)
      ["text-body", "surface-raised"], // scrubber readout + Play button on the scrubber bar
      ["text-muted", "surface-raised"], // the "frame" label on the scrubber bar
      ["text-body", "surface-muted"], // the Compare RMSD overlay caption on its well fill
      ["text-muted", "surface"], // the species-legend rows and the cell-less caption
      // The metadata chip: `text-muted` on the `bg-well` fill — the app-wide inert-chip pairing
      // (RecentsStrip source note + format tag, JobPhase, DecisionCard, SamplePicker, the report
      // panels, PresetManager, …). `text-faint` on this same fill only reaches ~4.34:1 light /
      // ~4.04:1 dark, so it is *not* legible here — the whole-page axe scan caught a RecentsStrip
      // chip that used it; guarding the canonical `text-muted` pair keeps that from recurring.
      ["text-muted", "surface-muted"],
    ] as const)("viewer chrome %s clears AA on %s", (fg, bg) => {
      expect(contrast(t(fg), t(bg))).toBeGreaterThanOrEqual(AA);
    });

    // The workbench chrome surfaces (v2.0 addendums Task 6 — Steel dark-first theme, design spec
    // "Theme system"): the toolbar, source rail, main panel, and status bar each get their own
    // token so the shell can band them distinctly from the plain page `--surface`. Body and heading
    // text must still clear AA rendered directly on each one, in both themes.
    it.each(["wb-toolbar", "wb-rail", "wb-panel", "wb-status"])(
      "text-body clears AA on workbench chrome surface %s",
      (name) => {
        expect(contrast(t("text-body"), t(name))).toBeGreaterThanOrEqual(AA);
      },
    );
    it.each(["wb-toolbar", "wb-rail", "wb-panel", "wb-status"])(
      "text-strong clears AA on workbench chrome surface %s",
      (name) => {
        expect(contrast(t("text-strong"), t(name))).toBeGreaterThanOrEqual(AA);
      },
    );

    // The global keyboard-focus ring (v2.0 addendums item 5, the dark-palette focus pass): the
    // `:focus-visible` baseline in globals.css draws a `--accent` outline wrapped in an `--inverse`
    // halo. The accent tone is kept dark for white-on-accent AA, so accent-on-surface only reaches
    // ~3:1 on the darkest chrome; the halo is what guarantees the ring stays visible on any surface.
    // Guard both the halo↔surface boundary (on every surface a bare interactive element can sit on)
    // and the halo↔accent boundary (the two-tone ring's own internal edge), in both themes, at the
    // WCAG 1.4.11 non-text bar. A future accent/inverse edit that would sink the ring below 3:1 fails
    // here instead of silently regressing focus visibility.
    it.each(["surface", "surface-raised", "surface-muted"])(
      "the focus-ring halo (--inverse) clears the non-text bar on %s",
      (bg) => {
        expect(contrast(t("inverse"), t(bg))).toBeGreaterThanOrEqual(FOCUS);
      },
    );
    it("the focus ring's accent↔halo internal edge clears the non-text bar", () => {
      expect(contrast(t("accent"), t("inverse"))).toBeGreaterThanOrEqual(FOCUS);
    });
  });
}

describe("UI palette — WCAG AA contrast", () => {
  checkTheme("light", lightBlock);
  checkTheme("dark", darkBlock);
});

describe("paper surface (redesign §9)", () => {
  it("shares the light theme's declaration list via the `:root, [data-surface=\"paper\"]` selector", () => {
    expect(css).toMatch(/:root\s*,\s*\[data-surface="paper"\]\s*\{/);
  });
});

/**
 * The default-theme contract (redesign D-B7, reversing the D300 dark-first default): the theme
 * follows the OS unless the user chose otherwise. Two places encode the resolution and must agree —
 * the no-flash script in `app/layout.tsx` (runs before paint) and `ThemeProvider` (runs after
 * hydration) — so both are read from source here, matching this file's "parse the real source"
 * approach. The SSR `<html data-theme>` is only a placeholder the script overwrites.
 */
describe("default theme — follows the system (redesign D-B7)", () => {
  const layoutSrc = readFileSync(resolve(process.cwd(), "app/layout.tsx"), "utf8");
  const providerSrc = readFileSync(resolve(process.cwd(), "lib/theme/ThemeProvider.tsx"), "utf8");

  it("the no-flash script consults prefers-color-scheme", () => {
    expect(layoutSrc).toContain("matchMedia('(prefers-color-scheme: dark)')");
  });

  it("an explicit persisted light/dark wins; anything else resolves from the OS", () => {
    expect(layoutSrc).toMatch(/t==='light'\|\|t==='dark'\?t:sys\(\)/);
  });

  it("an unreadable localStorage also resolves from the OS, never a fixed scheme", () => {
    expect(layoutSrc).toMatch(/catch\(e\)\{d\.setAttribute\('data-theme',sys\(\)\)/);
  });

  it("ThemeProvider's preference defaults to system and resolves through the same query", () => {
    expect(providerSrc).toContain('const DARK_QUERY = "(prefers-color-scheme: dark)"');
    expect(providerSrc).toMatch(/useState<ThemePreference>\(\(\)\s*=>\s*\n?\s*typeof window === "undefined" \? "system" : readStoredPreference\(\)/);
  });
});
