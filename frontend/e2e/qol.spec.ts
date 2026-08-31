import { expect, test } from "@playwright/test";

/**
 * The S4 quality-of-life layer journey (MASTER_SPEC Part 7; UI redesign S4, D246; design spec §6)
 * — all client-side, driven in the browser over the live stack:
 *
 *  1. **⌘K** opens a focus-keeping, closable command palette. Opening moves focus into the dialog;
 *     Tab moves *within* the dialog (it never leaks to the page behind); Escape closes it.
 *  2. **A sample file completes a conversion end-to-end**: "Start with a sample" uploads a vendored
 *     fixture through the normal upload path and the result lands in the workspace, then converts.
 *  3. **A saved preset re-converts**: save the current target + posture under a name, and the
 *     "Re-convert" button starts a fresh conversion without re-choosing.
 *
 * These are the slice's done-means journeys, each asserting a *localStorage-only* capability — no
 * new backend route is touched beyond the standard convert/inspect/upload flow.
 */
test("⌘K opens the palette, keeps focus inside it, and Escape closes (S4)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();

  // Open with the global shortcut, exactly as a user would.
  await page.keyboard.press("Meta+K");
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  await expect(dialog).toBeVisible({ timeout: 30_000 });
  const input = page.getByLabel("Search commands");
  await expect(input).toBeFocused();

  // Focus stays inside the dialog: a Tab from the input lands on a result (still inside), not the
  // page's header — the trap the palette is required to maintain.
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.closest("[role=dialog]") !== null);
  expect(focused, "after Tab, focus must still be inside the dialog").toBe(true);

  // Escape closes it and focus returns to the page (the trigger).
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Command palette" })).not.toBeVisible();
});

test("a sample file completes a conversion end-to-end via the normal upload path (S4)", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();

  // "Start with a sample": the vendored water.xyz uploads through the same `useUpload` path as a
  // dropped file, so it must land in the file's workspace (the Inspect tab).
  await page.getByTestId("sample-water").click();
  await page.waitForURL(/\/f\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "water.xyz" })).toBeVisible({ timeout: 30_000 });

  // Advance the guided spine to the Convert tab and commit a lossless conversion (water → plain XYZ).
  await page.getByRole("link", { name: "Convert →" }).click();
  await expect(page.getByRole("heading", { name: "Convert", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Plain XYZ", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to Plain XYZ/ }).click();
  await page.getByRole("button", { name: "Convert", exact: true }).click();

  // The conversion runs off the queue and polls to completion; when it lands, the durable record
  // (with its loss report) is one click away — the sample's conversion is complete end-to-end.
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 60_000 });
  await recordLink.click();
  await expect(page).toHaveURL(/\/report\/[^/]+/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /^Converted —/ })).toBeVisible();
});

test("a saved preset re-converts in one click (S4)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();

  // Upload a sample, then go to the Convert tab to pick a target.
  await page.getByTestId("sample-diatomic").click();
  await page.waitForURL(/\/f\/[^/]+$/);
  await page.getByRole("link", { name: "Convert →" }).click();
  await expect(page.getByRole("heading", { name: "Convert", exact: true })).toBeVisible();

  // Choose VASP POSCAR (a lossy target for the extXYZ sample) and save it as a named preset.
  await page.getByRole("button", { name: "VASP POSCAR", exact: true }).click();
  await page.getByLabel("Preset name").fill("poscar from sample");
  await page.getByRole("button", { name: "Save preset" }).click();
  await expect(page.getByTestId("preset-list")).toContainText("poscar from sample");

  // One-click re-convert: the preset's Re-convert starts a fresh conversion (routes to the job).
  await page.getByRole("button", { name: "Re-convert" }).click();
  await expect(page).toHaveURL(/convert\?job=/, { timeout: 30_000 });
  // The re-launched job is the polled, completed conversion — its record link proves the convert ran.
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 60_000 });
});