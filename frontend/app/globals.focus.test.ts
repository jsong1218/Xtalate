import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The global keyboard-focus indicator guard (pre-M36 frontend-redesign addendum, Slice S6; design
 * spec §4.6). The a11y sweep's load-bearing, app-wide change is a single `:focus-visible` baseline in
 * `globals.css`: every interactive element a component author did *not* give a bespoke Tailwind ring
 * (form inputs, the ack checkbox, the recovery radios, native `<summary>` disclosures, doc-markdown
 * links) still shows a consistent, visible focus outline under keyboard navigation, instead of the
 * inconsistent browser default. The bespoke component rings (Button, AppHeader, BackLink, the theme
 * toggle) keep winning because they live in Tailwind's utilities layer and set `outline-none` there,
 * which beats this base-layer rule — so there is never a double indicator.
 *
 * This test reads the *actual* stylesheet (jsdom can't compute `:focus-visible`, and the value here is
 * the source text, not a rendered pixel) and fails CI if the baseline is removed or unhooked from the
 * theme accent — so the focus indicator can't silently regress the way it had before this slice.
 */

// Vitest runs from the frontend package root; resolve the stylesheet from there. Comments are stripped
// so the file's prose (which mentions ":focus-visible" and "@layer base") can't satisfy the assertions.
const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);

/** The `@layer base { … }` block, where the baseline must live so utility rings override it. */
function baseLayer(): string {
  const match = /@layer\s+base\s*\{([\s\S]*)\}/.exec(css);
  if (!match) throw new Error("@layer base block not found in globals.css");
  return match[1];
}

describe("global keyboard-focus baseline (addendum §4.6)", () => {
  it("defines a :focus-visible rule inside @layer base", () => {
    const layer = baseLayer();
    expect(/:focus-visible\s*\{[\s\S]*?\}/.test(layer)).toBe(true);
  });

  it("draws the focus outline in the theme accent, so it flips with the theme", () => {
    const rule = /:focus-visible\s*\{([\s\S]*?)\}/.exec(baseLayer());
    if (!rule) throw new Error(":focus-visible rule not found in @layer base");
    const body = rule[1];
    // A real, visible outline (not `none`/transparent) bound to the accent token, offset off the box.
    expect(body).toMatch(/outline:[^;]*var\(--accent\)/);
    expect(body).toMatch(/outline-offset:/);
  });
});
