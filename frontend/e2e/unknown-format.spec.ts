import { expect, test } from "@playwright/test";
import { fixturePath, FIXTURES } from "./support/api";

/**
 * Negative journey — an unrecognized file (MASTER_SPEC Part 7 §5 item 4; slice M30-S1). Uploading a
 * Word document (its ZIP byte signature, no chemistry in it) succeeds as a *transfer* — the upload
 * endpoint stores bytes and does not sniff — but the inspection that the file page runs cannot
 * identify a format, so the service answers `UNKNOWN_FORMAT`. The honest state is the error envelope
 * with that machine code shown **verbatim**, not a guess and not a blank page.
 */
test("an unrecognized file inspects to a verbatim UNKNOWN_FORMAT envelope", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Choose a file to convert")
    .setInputFiles(fixturePath(FIXTURES.notAStructure.file));

  // The transfer succeeds and the app routes to the file's workspace; inspection is what refuses.
  await page.waitForURL("**/f/**");

  // The code is rendered as a verbatim badge (Part 6 §6) — a support thread and the screen match.
  await expect(page.getByText("UNKNOWN_FORMAT", { exact: true })).toBeVisible({ timeout: 30_000 });
  // And the page offers the honest way forward rather than dead-ending on the error.
  await expect(page.getByRole("link", { name: /Upload a different file/i })).toBeVisible();
});
