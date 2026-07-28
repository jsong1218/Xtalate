import { expect, test } from "@playwright/test";

/**
 * Smoke test: the app shell serves and the primary action is present (D92). The full journeys and
 * the honest negative cases live in their own specs beside this one (M30-S1, Part 7 §5); this stays
 * as the fastest possible "is the frontend even up" check.
 */
test("landing shell serves with the primary action", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Convert a file" })).toBeVisible();
});
