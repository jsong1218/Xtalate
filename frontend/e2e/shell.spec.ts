import { expect, test } from "@playwright/test";

/**
 * M26 smoke test: the app shell serves and the primary action is present. The full journeys
 * (upload → inspect → convert → record → download) and the honest negative cases are filled in at
 * M30 (Part 7 §5 verification list); this proves the Playwright harness (D92) is wired.
 */
test("landing shell serves with the primary action", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Convert a file" })).toBeVisible();
});
