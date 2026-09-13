import { expect, test } from "@playwright/test";
import { FIXTURES, uploadFixture } from "./support/api";

/**
 * The Analysis tab journey (v1.8 M70, Part 7 §6): the tab reads `GET /v1/plugins`, offers the
 * installed analysis plugins, runs the chosen one via `POST /v1/analyze`, and renders the
 * namespaced results through the generic renderer. This proves the whole seam over the running
 * stack — the composition reference plugin is installed in the compose image (Dockerfile), so the
 * picker is populated, the analyze job runs on the real worker, and the report reaches the browser.
 *
 * The fixture is a **cell-less** water trajectory (`FIXTURES.noCellXyz`), chosen so one run
 * exercises both honesty rules at once (P1, P3): a value the plugin *can* compute (the Hill formula
 * `H2O`) and one it honestly *cannot* (mass density — the source declares no simulation cell), which
 * must render as "not computed" alongside the plain-language note that says why. A blank cell or a
 * dropped row would be the silent loss the whole product exists to prevent.
 */
test("the Analysis tab runs the composition plugin and renders results with honest absence", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.noCellXyz);

  await page.goto(`/f/${fileId}/analysis`);
  await expect(
    page.getByRole("heading", { name: "Analysis", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  // The roster arrived and the picker defaulted to the installed composition plugin.
  const picker = page.getByRole("combobox", { name: "Analysis plugin" });
  await expect(picker).toBeVisible({ timeout: 30_000 });
  await expect(picker).toHaveValue("composition");

  // Run it; the analyze job goes through the real worker and the report comes back.
  await page.getByRole("button", { name: "Run analysis" }).click();

  // A value the plugin computed: the reduced Hill formula for the water trajectory.
  await expect(page.getByText("H2O", { exact: true })).toBeVisible({ timeout: 60_000 });

  // A value it honestly could not compute — no cell in the source — renders as "not computed",
  // never a blank, alongside the plain-language reason (P1, P3).
  await expect(page.getByText("not computed", { exact: true })).toBeVisible();
  await expect(page.getByText(/no simulation cell declared in the source/i)).toBeVisible();
});
