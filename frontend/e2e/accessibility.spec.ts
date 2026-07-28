import { expect, test, type Page } from "@playwright/test";
import happyRecord from "../components/__fixtures__/conversion.record.json";

/**
 * Automated WCAG 2.1 A/AA checks in a real browser (MASTER_SPEC Part 7 §4–§5; slice M30-S2). jsdom
 * cannot judge rendered contrast or focus order, so this runs **axe-core** (already a dependency, so
 * no new package) against the real pages and fails on any *serious or critical* barrier — the
 * category that includes color-contrast, missing accessible names, and ARIA misuse. The token-level
 * contrast is additionally pinned dependency-free in `app/globals.contrast.test.ts`; this is the
 * whole-page check that catches a barrier the isolated tokens cannot (a foreground on an unexpected
 * surface, a control with no name).
 *
 * The dense, color-coded page — the conversion record, with its preserved/removed/assumption
 * palette, both report panels, and the provenance strip — is exercised from the real captured record
 * body, so the scan is deterministic and needs no worker run.
 */

async function seriousViolations(page: Page): Promise<{ id: string; help: string }[]> {
  // Playwright transpiles specs to CommonJS, so the global `require` resolves axe-core from
  // node_modules — no new dependency, and the browser gets the same engine axe ships.
  await page.addScriptTag({ path: require.resolve("axe-core") });
  const result = await page.evaluate(async () => {
    // axe is injected onto window by the script tag above.
    const axe = (window as unknown as { axe: { run: (ctx: Document, opts: unknown) => Promise<unknown> } }).axe;
    return (await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    })) as { violations: { id: string; impact: string | null; help: string }[] };
  });
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({ id: v.id, help: v.help }));
}

test("the landing page has no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();

  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});

test("the conversion record page has no serious accessibility violations", async ({ page }) => {
  // Render a full, loss-carrying record from the real captured body — the page's whole palette on
  // screen at once (summary chips, both report panels, download, provenance).
  await page.route("**/v1/conversions/**", (route) => route.fulfill({ json: happyRecord }));
  await page.goto(`/conversions/${(happyRecord as { conversion_id: string }).conversion_id}`);
  await expect(page.getByRole("heading", { name: /^Converted/ })).toBeVisible();

  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});
