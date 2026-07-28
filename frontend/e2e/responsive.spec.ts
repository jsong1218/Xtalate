import { expect, test, type Page } from "@playwright/test";
import { fixturePath, FIXTURES } from "./support/api";
import happyRecord from "../components/__fixtures__/conversion.record.json";

/**
 * Responsive pass (MASTER_SPEC Part 7 §2.5, §5; slice M30-S2). Two things the spec calls out: the
 * record's Conversion and Validation panels sit **side by side on a wide screen and stacked on a
 * narrow one**, and dense content (the inventory table) must not force the page to scroll sideways on
 * a phone. Both are real-layout properties, so they are asserted against rendered geometry in a real
 * browser, not inferred from class names.
 */

const RECORD_ID = (happyRecord as { conversion_id: string }).conversion_id;

/** No page should scroll horizontally: its content fits the viewport width (a 1px rounding slack). */
async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "the page must not scroll horizontally").toBeLessThanOrEqual(1);
}

test("the report panels stack on a phone and sit side by side on a desktop", async ({ page }) => {
  await page.route("**/v1/conversions/**", (route) => route.fulfill({ json: happyRecord }));

  const columns = page.locator('[data-testid="report-columns"] > *');

  // Phone: one column — the second panel sits *below* the first, at the same left edge.
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto(`/conversions/${RECORD_ID}`);
  await expect(page.getByTestId("report-columns")).toBeVisible();
  const mTop = await columns.nth(0).boundingBox();
  const mBottom = await columns.nth(1).boundingBox();
  expect(mBottom!.y).toBeGreaterThan(mTop!.y + mTop!.height - 1); // fully below, not beside
  expect(Math.abs(mBottom!.x - mTop!.x)).toBeLessThan(2); // same left edge
  await assertNoHorizontalOverflow(page);

  // Desktop: two columns — the second panel sits to the *right* of the first, roughly level with it.
  await page.setViewportSize({ width: 1280, height: 900 });
  const dLeft = await columns.nth(0).boundingBox();
  const dRight = await columns.nth(1).boundingBox();
  expect(dRight!.x).toBeGreaterThan(dLeft!.x + dLeft!.width - 1); // beside, not below
  expect(Math.abs(dRight!.y - dLeft!.y)).toBeLessThan(2); // level tops
});

test("no wizard page scrolls sideways on a phone, inventory table included", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });

  await page.goto("/");
  await assertNoHorizontalOverflow(page);

  await page.goto("/convert");
  await assertNoHorizontalOverflow(page);

  // The inventory table is the densest thing on a phone; inspect a real file and check it fits.
  await page
    .getByLabel("Choose a file to convert")
    .setInputFiles(fixturePath(FIXTURES.workedExample.file));
  await page.waitForURL("**/files/**");
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });
  await assertNoHorizontalOverflow(page);
});
