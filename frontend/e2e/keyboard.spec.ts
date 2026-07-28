import { expect, test } from "@playwright/test";
import { fixturePath, FIXTURES } from "./support/api";

/**
 * Keyboard traversal of the wizard (MASTER_SPEC Part 7 §4; slice M30-S2). A conversion must be
 * completable without a mouse: focus must reach the primary controls in a sensible order, and they
 * must activate on Enter. This drives the real browser's focus model — Tab order and Enter
 * activation — which jsdom cannot represent.
 */

test("the primary path is reachable and operable by keyboard from the landing page", async ({
  page,
}) => {
  await page.goto("/");

  // The first Tab lands on the primary call to action, and Enter follows it — no mouse needed.
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText(/Convert a file/);
  await page.keyboard.press("Enter");
  await page.waitForURL("**/convert");

  // On the upload step the first control is the file chooser, with a real accessible name.
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText(/Choose a file/);
});

test("the conversion can be chosen and started with the keyboard", async ({ page }) => {
  // Reach an inspected file (setting the file is the OS picker's job; everything after is keyboard).
  await page.goto("/convert");
  await page
    .getByLabel("Choose a file to convert")
    .setInputFiles(fixturePath(FIXTURES.workedExample.file));
  await page.waitForURL("**/files/**");
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });

  // Select the target by focusing it and pressing Enter — the button reflects the choice via
  // aria-pressed, so a screen-reader user hears the selection, not just sees a color change.
  const target = page.getByRole("button", { name: "Plain XYZ", exact: true });
  await target.focus();
  await page.keyboard.press("Enter");
  await expect(target).toHaveAttribute("aria-pressed", "true");

  // Start the conversion from the keyboard; the wizard advances to the live job page.
  const convert = page.getByRole("button", { name: /^Convert to Plain XYZ$/ });
  await convert.focus();
  await page.keyboard.press("Enter");
  await page.waitForURL("**/convert/**");
});
