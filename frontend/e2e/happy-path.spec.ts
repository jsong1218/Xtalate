import { expect, test } from "@playwright/test";
import { fixturePath, FIXTURES } from "./support/api";

/**
 * The full happy path, end to end in a real browser against the compose stack (MASTER_SPEC Part 7
 * §5, verification item 1; slice M30-S1). This is the journey the "non-programmer completes a
 * conversion and reads what happened" bar is written against, so it is driven entirely through the
 * UI — no API shortcuts — from the landing page to the downloaded file:
 *
 *     landing → upload → inspect → choose target → convert → record → download
 *
 * The upload is an **extended XYZ** carrying a lattice, forces, charge, masses and an energy; the
 * target is **plain XYZ**, which can hold none of those. So this is not a lossless round-trip — it
 * is the worked example of the product's whole reason to exist: the record page must state, in
 * plain quantitative language, exactly what plain XYZ dropped, and it must do so *above* the
 * download control. A reader cannot reach the button without passing what the conversion cost.
 */
test("upload → inspect → convert → record → download, extXYZ to XYZ", async ({ page }) => {
  // 1. Landing → the upload step.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();
  await page.getByRole("link", { name: "Convert a file" }).click();

  // 2. Upload the extended-XYZ worked example. The file input is visually hidden but present; a
  //    real click would open the OS picker, so the test sets the file directly, as the drop would.
  await expect(page.getByRole("heading", { name: "Convert a file" })).toBeVisible();
  await page.getByLabel("Choose a file to convert").setInputFiles(fixturePath(FIXTURES.workedExample.file));

  // 3. Inspection: the app routes to the file resource and shows what the file actually contains.
  await page.waitForURL("**/files/**");
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });

  // 4. Choose plain XYZ as the target, then commit the conversion (permissive is the default).
  await page.getByRole("button", { name: "Plain XYZ", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to Plain XYZ$/ }).click();

  // 5. The live job page. The worker runs the job off the queue, so this polls to completion; when
  //    it lands, the durable record is one link away (the download deliberately lives only there).
  await page.waitForURL("**/convert/**");
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 30_000 });
  await recordLink.click();

  // 6. The record page. The outcome header is quantitative and never celebratory: plain XYZ dropped
  //    the lattice, forces, charge and energy, so the header names removed fields — not "Done!".
  await page.waitForURL("**/conversions/**");
  await expect(page.getByRole("heading", { name: /^Converted — .*removed/ })).toBeVisible();

  // 7. The layout law, asserted against real rendered geometry: the loss summary sits *above* the
  //    download panel. A refactor that hoisted the button into the header would fail here.
  const summary = page.getByTestId("summary-chips");
  const download = page.getByTestId("download-panel");
  await expect(summary).toBeVisible();
  await expect(download).toBeVisible();
  const summaryBox = await summary.boundingBox();
  const downloadBox = await download.boundingBox();
  expect(summaryBox, "summary chips must render").not.toBeNull();
  expect(downloadBox, "download panel must render").not.toBeNull();
  expect(summaryBox!.y, "the loss summary must sit above the download control").toBeLessThan(
    downloadBox!.y,
  );

  // 8. Take the file. saveBlob hands the fetched bytes to the browser as a download; capture it and
  //    confirm the service named a real XYZ output.
  const downloadButton = page.getByRole("button", { name: /^Download / });
  await expect(downloadButton).toBeVisible();
  const [saved] = await Promise.all([
    page.waitForEvent("download"),
    downloadButton.click(),
  ]);
  expect(saved.suggestedFilename()).toMatch(/\.xyz$/);
});
