import { expect, test, type APIRequestContext } from "@playwright/test";
import { API_URL, FIXTURES, pollJob, uploadFixture } from "./support/api";

/**
 * The S3 report redesign journey (MASTER_SPEC Part 7 §4.3; UI redesign S3, D245; design spec §5
 * + §9's no-loss invariant).
 *
 * The guard is **the no-loss invariant, proven in the browser over the live stack**: the redesigned
 * report shows the same set of rows/outcomes as the engine's report model for a known conversion —
 * nothing filtered away by default, and a forced-loss conversion (extXYZ → POSCAR: the target
 * *cannot* store forces/energy) still renders its lost rows, reasons verbatim.
 *
 * The journey is data-driven: it reads the conversion record from the API and asserts the rendered
 * row set against the model's own arrays, so it adapts to whatever the seed actually produced
 * rather than hard-coding a fixture's counts. It also walks the three new affordances — outcome
 * grouping order, a filter narrowing then restoring, and Copy-as-JSON / Copy-link producing the
 * expected strings.
 */

/** A forced-loss conversion: the worked example (extXYZ with lattice/forces/charge/energy) → POSCAR. */
async function seedForcedLoss(
  request: APIRequestContext,
): Promise<{ conversionId: string; fileId: string }> {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  const resp = await request.post(`${API_URL}/v1/convert`, {
    data: {
      file_id: fileId,
      target_format_id: "poscar",
      options: { allow_recovery: true },
    },
  });
  expect([200, 201, 202]).toContain(resp.status());
  const jobId = String((await resp.json()).job_id);
  const done = await pollJob(request, jobId, ["completed"]);
  expect(done.state).toBe("completed");
  const result = done.result as { conversion_id?: string };
  const conversionId = String(result.conversion_id);
  expect(conversionId).toBeTruthy();
  return { conversionId, fileId };
}

/** Read the conversion record's report model straight from the wire — the ground truth to assert against. */
/** The report-model fields the journey asserts against (the rest of the model is exported verbatim). */
interface ReportModel {
  removed: { path: string; reason: string }[];
  preserved: unknown[];
  assumptions: unknown[];
  warnings: unknown[];
}

/** Read the conversion record's report model straight from the wire — the ground truth to assert against. */
async function readReportModel(
  request: APIRequestContext,
  conversionId: string,
): Promise<ReportModel> {
  const resp = await request.get(`${API_URL}/v1/conversions/${conversionId}`);
  expect(resp.ok(), await resp.text()).toBeTruthy();
  const record = (await resp.json()) as { conversion_report: ReportModel };
  return record.conversion_report;
}

test("the S3 report: no-loss invariant, outcome order, filter narrow/restore, category toggle, export", async ({
  page,
  request,
  context,
}) => {
  // Clipboard for the export assertions (localhost is a secure context; the app writes through
  // navigator.clipboard). Both the JSON body and the permalink are asserted from the clipboard.
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);

  const { conversionId, fileId } = await seedForcedLoss(request);
  const model = await readReportModel(request, conversionId);
  // The seed must actually exercise the invariant: a conversion with nothing lost would make the
  // forced-loss assertions vacuous. The worked example → POSCAR cannot carry forces/energy.
  expect(model.removed.length, "the forced-loss seed must lose fields").toBeGreaterThan(0);

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  const panel = page.getByTestId("report-columns").first();

  // 1. Outcome grouping order — the section headings must appear Assumed → Lost → Warned → Kept
  //    (whatever is present in this model), top to bottom.
  const sectionOrder = ["Assumed", "Lost", "Warned", "Kept"] as const;
  const present = sectionOrder.filter((title) => {
    const count =
      title === "Kept"
        ? model.preserved.length
        : title === "Lost"
          ? model.removed.length
          : title === "Warned"
            ? model.warnings.length
            : model.assumptions.length;
    return count > 0;
  });
  const headingBoxes = await Promise.all(
    present.map(async (title) => {
      const heading = panel.getByRole("heading", { name: new RegExp(`^${title}\\s+\\(`) });
      await expect(heading).toBeVisible({ timeout: 30_000 });
      const box = await heading.boundingBox();
      expect(box, `heading ${title} must render`).not.toBeNull();
      return { title, y: box!.y };
    }),
  );
  for (let i = 1; i < headingBoxes.length; i += 1) {
    expect(
      headingBoxes[i].y,
      `outcome section order: ${headingBoxes[i - 1].title} must sit above ${headingBoxes[i].title}`,
    ).toBeGreaterThan(headingBoxes[i - 1].y);
  }

  // 2. The no-loss invariant: the default, unfiltered row set equals the model's full row set.
  await expect(panel.getByTestId("removed-row")).toHaveCount(model.removed.length, { timeout: 30_000 });
  await expect(panel.getByTestId("preserved-row")).toHaveCount(model.preserved.length);
  await expect(panel.getByTestId("assumption-row")).toHaveCount(model.assumptions.length);
  await expect(panel.getByTestId("warning-row")).toHaveCount(model.warnings.length);

  // 3. The forced loss is visible, reason verbatim — the report's own words, never a paraphrase.
  const forced = model.removed[0];
  await expect(panel.getByText(forced.reason)).toBeVisible();

  // 4. A filter narrows the *visible* rows only — and restoring All brings the full set back.
  await panel.getByRole("button", { name: /^Kept\s+\d/ }).click();
  await expect(panel.getByTestId("removed-row")).toHaveCount(0);
  await expect(panel.getByText(forced.reason)).not.toBeVisible();
  await expect(panel.getByTestId("preserved-row")).toHaveCount(model.preserved.length);

  await panel.getByRole("button", { name: /^All\s+\d/ }).click();
  await expect(panel.getByTestId("removed-row")).toHaveCount(model.removed.length);
  await expect(panel.getByText(forced.reason)).toBeVisible();

  // 5. Category grouping: the same rows, re-organized — none dropped by the toggle.
  await panel.getByRole("button", { name: "Category" }).click();
  await expect(panel.getByTestId("removed-row")).toHaveCount(model.removed.length);
  await expect(panel.getByTestId("preserved-row")).toHaveCount(model.preserved.length);
  await expect(panel.getByTestId("assumption-row")).toHaveCount(model.assumptions.length);

  // 6. Copy-as-JSON produces the report model verbatim (pretty-printed, but the same document).
  await panel.getByRole("button", { name: "Copy as JSON" }).click();
  await expect(panel.getByRole("button", { name: "Copied" })).toBeVisible();
  const jsonText = await page.evaluate(() => navigator.clipboard.readText());
  expect(JSON.parse(jsonText)).toEqual(model);

  // 7. Copy-link yields the durable workspace permalink.
  await panel.getByRole("button", { name: "Copy link" }).click();
  const linkText = await page.evaluate(() => navigator.clipboard.readText());
  expect(linkText).toBe(`/f/${fileId}/report/${conversionId}`);
});
