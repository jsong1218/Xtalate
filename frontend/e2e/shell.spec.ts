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

/**
 * The persistent header (pre-M36 addendum S2): a home wordmark and the primary destinations, present
 * on every page. This is the navigation that replaced the old per-page inline links.
 */
test("the header carries the primary navigation on every page", async ({ page }) => {
  await page.goto("/history");
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("link", { name: "Xtalate" })).toHaveAttribute("href", "/");
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (const label of ["Convert", "Formats", "History", "Docs"]) {
    await expect(nav.getByRole("link", { name: label })).toBeVisible();
  }
});

/**
 * The theme toggle (addendum S1 mechanism, S2 mount): flips `data-theme` on <html> and persists the
 * choice across a reload. The token-level contrast of both themes is guarded in vitest; this proves
 * the switch is wired into the running app and sticks.
 */
test("the theme toggle switches to dark and the choice persists", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");

  await page.getByRole("button", { name: /switch to dark mode/i }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");

  // Persisted: a reload comes back dark, with no flash of light (the no-FOUC script applies it).
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
});

/**
 * The consistent back affordance (addendum S2): an explicit parent destination in the upper-left of
 * every non-landing page, never raw browser-back, so the user is never trapped.
 */
test("a sub-page offers a back link to its parent route", async ({ page }) => {
  await page.goto("/convert");
  await page.getByRole("link", { name: "Back to Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();
});
