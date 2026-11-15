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
 * The persistent toolbar (v2.0 addendums Task 8, superseding the pre-M36 `AppHeader`): a home
 * wordmark and the primary destinations, present on every page. Formats/History/Docs live in the
 * "Primary" nav (the right cluster); Open/Upload and the contextual Convert verb live in their own
 * "File actions" nav (the left cluster, next to the wordmark) — two distinctly-labeled nav
 * landmarks, not one (Toolbar.tsx's own "two distinctly-labeled nav landmarks" note).
 */
test("the toolbar carries the primary navigation on every page", async ({ page }) => {
  await page.goto("/history");
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("link", { name: "Xtalate" })).toHaveAttribute("href", "/");
  const primary = page.getByRole("navigation", { name: "Primary" });
  for (const label of ["Formats", "History", "Docs"]) {
    await expect(primary.getByRole("link", { name: label })).toBeVisible();
  }
  const fileActions = page.getByRole("navigation", { name: "File actions" });
  await expect(fileActions.getByRole("link", { name: /open.*upload/i })).toHaveAttribute(
    "href",
    "/",
  );
  // /history is not a /f/[file_id] route, so there is no active file — Convert is an inert,
  // genuinely disabled button rather than a link to nowhere (Toolbar.tsx, P1).
  await expect(fileActions.getByRole("button", { name: "Convert" })).toBeDisabled();
});

/**
 * The theme control (redesign D-B7): three states, System · Light · Dark. With no stored choice the
 * page follows the OS scheme live; an explicit choice pins the theme and persists across a reload
 * (applied before paint by the no-flash script). Playwright emulates the OS scheme.
 */
test("the theme follows the system until a choice is made, and the choice persists", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");

  // Live OS change while the preference is "system".
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveAttribute("data-theme", "dark");

  // An explicit choice pins the theme regardless of the OS…
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Use light theme" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: "Use light theme" })).toHaveAttribute("aria-pressed", "true");

  // …and persists: a reload under a dark OS comes back light with no flash.
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "light");
});

/**
 * The completion-signal mute toggle (v1.1 M39-S4 C1): a bell in the header that mutes the chime +
 * notification, on by default and persisted across a reload. The sound/notification themselves are
 * browser-owned surfaces asserted in vitest with mocks; this proves the toggle renders in the live
 * app and the choice sticks.
 */
test("the completion-signal mute toggle renders, defaults on, and persists", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Mute completion signal" });
  await expect(toggle).toHaveAttribute("aria-pressed", "true");

  await toggle.click();
  await expect(page.getByRole("button", { name: "Unmute completion signal" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );

  // Persisted: a reload comes back muted, and the completion signal still doesn't crash the page.
  await page.reload();
  await expect(page.getByRole("button", { name: "Unmute completion signal" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();
});

/**
 * The consistent back affordance (addendum S2): an explicit parent destination in the upper-left of
 * every non-landing page, never raw browser-back, so the user is never trapped.
 */
test("a sub-page offers a back link to its parent route", async ({ page }) => {
  // With `/convert` redirected to the landing (UI redesign S2), the history list is a stable
  // sub-page carrying the consistent back affordance.
  await page.goto("/history");
  await page.getByRole("link", { name: "Back to Home" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();
});
