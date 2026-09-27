import { expect, test, type Page } from "@playwright/test";
import { fixturePath, FIXTURES, uploadFixture } from "./support/api";
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
  // Narrowed to the record itself (`*`, no `/`): the Structure tab's geometry request (M60) must
  // not receive the record body — the tab renders its own honest state from the live endpoint.
  await page.route("**/v1/conversions/*", (route) => route.fulfill({ json: happyRecord }));

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

  await page.goto("/history");
  await assertNoHorizontalOverflow(page);

  // The inventory table is the densest thing on a phone; back on the landing, upload a real file
  // and check the resulting workspace fits.
  await page.goto("/");
  await page
    .getByLabel("Choose a file to convert")
    .setInputFiles(fixturePath(FIXTURES.workedExample.file));
  await page.waitForURL("**/f/**");
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });
  await assertNoHorizontalOverflow(page);
});

/**
 * The workbench collapse rules (v2.0 addendums Task 13; design spec §"Region behaviors &
 * responsiveness": "below `md`, the Sources rail and Inspector collapse to icon rails / are hidden
 * behind toggles ... The center is never hidden"). Below their respective breakpoints, the rail and
 * inspector are not merely CSS-dimmed — they are outside the accessibility tree entirely
 * (`display:none`, so `getByRole` finds nothing) until their own reachable toggle opens them as an
 * overlay; the center content is visible throughout.
 */
test("the Sources rail and Inspector collapse behind reachable toggles below their breakpoints", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  await page.setViewportSize({ width: 375, height: 900 }); // below both `md` (768) and `lg` (1024)
  await page.goto(`/f/${fileId}`);
  await expect(page.getByText(/^Detected\s/)).toBeVisible({ timeout: 30_000 }); // center never hidden

  // Sources rail: closed by default below `md` — the landmark itself is unreachable, not just
  // visually dimmed — until its own toggle (rendered outside the collapsed `nav`) opens it.
  const showSources = page.getByRole("button", { name: /^show sources$/i });
  await expect(showSources).toBeVisible();
  await expect(showSources).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("navigation", { name: "Sources" })).toBeHidden();
  await showSources.click();
  const sourcesNav = page.getByRole("navigation", { name: "Sources" });
  await expect(sourcesNav).toBeVisible();
  await expect(page.getByRole("button", { name: /^hide sources$/i })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await page.getByRole("button", { name: /^hide sources$/i }).click();
  await expect(sourcesNav).toBeHidden();

  // Inspector: same pattern, its own breakpoint (`lg`) and its own toggle.
  const showInspector = page.getByRole("button", { name: /^show inspector$/i });
  await expect(showInspector).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Inspector" })).toBeHidden();
  await showInspector.click();
  const inspectorAside = page.getByRole("complementary", { name: "Inspector" });
  await expect(inspectorAside).toBeVisible();
  await expect(page.getByRole("button", { name: /^hide inspector$/i })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await page.getByRole("button", { name: /^hide inspector$/i }).click();
  await expect(inspectorAside).toBeHidden();

  // The center region was never hidden by any of the above.
  await expect(page.getByText(/^Detected\s/)).toBeVisible();
  await assertNoHorizontalOverflow(page);
});

/**
 * The toolbar's own condensing rule (design spec: "the toolbar condenses verbs into an overflow
 * menu" below `sm`). The labelled "File actions" nav (Open/Upload, Convert) is unreachable below
 * `sm`; the same two verbs are reachable instead behind a single "Menu" disclosure — never both at
 * once, so there is exactly one accessible "Open / Upload" control at a time. It is a disclosure of
 * ordinary links, not an ARIA `menu` (Task 13 review fix): it offers Tab-through + Escape +
 * outside-click, not the roving arrow-key model `role="menu"` would promise, so those roles stay off.
 */
test("the toolbar condenses its verbs into an overflow disclosure on a narrow viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 900 }); // below `sm` (640)
  await page.goto("/");

  await expect(page.getByRole("navigation", { name: "File actions" })).toBeHidden();
  const menuButton = page.getByRole("button", { name: "Menu" });
  await expect(menuButton).toBeVisible();
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");

  await menuButton.click();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  const panel = page.locator("#toolbar-overflow-menu");
  await expect(panel.getByRole("link", { name: /open.*upload/i })).toHaveAttribute("href", "/");
  // Off a /f/[file_id] route there is no active file: Convert is inert (aria-disabled), not a link.
  await expect(panel.getByText("Convert")).toHaveAttribute("aria-disabled", "true");

  // Exactly one accessible "Open / Upload" control exists at a time — the disclosure link, not a
  // CSS-hidden duplicate of the wide-viewport nav's own link (which is `display:none` below `sm`).
  await expect(page.getByRole("link", { name: /open.*upload/i })).toHaveCount(1);

  // Escape dismisses the disclosure (parity with the rail/inspector overlays; Task 13 review fix).
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");

  // The toggle also closes it.
  await menuButton.click();
  await expect(panel).toBeVisible();
  await menuButton.click();
  await expect(panel).toBeHidden();
});
