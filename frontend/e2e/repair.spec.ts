import { expect, test, type Page } from "@playwright/test";
import { cancelJob, FIXTURES, fixturePath } from "./support/api";

/**
 * The repair journeys (v1.7 M66-S3, D257) — a user-initiated repair driven through the pre-
 * conversion card on the workspace's Convert tab, its ⟳ "Modified on request" mark on the
 * completed record, and the Compare tab's before/after — free by construction from canonical
 * geometry (impl-plan §2.4).
 *
 * The flagship is entirely browser-driven: upload → Convert tab → add a `wrap_into_cell` card →
 * convert → record. The wrap transforms every atom into the cell *on request*, so the report must
 * show the ⟳ mark (a transformed value — not ◆ violet, which stays reserved for fabricated
 * values), the R5 warning in plain language (the transformative-loss statement, D251), and the
 * Compare tab must render before (source) vs after (output) — the same two canonical objects the
 * validator diffed.
 *
 * The other two journeys pin the two honesty edges of the surface: a **cell-less** wrap cannot
 * run (it would fabricate a box), so it pauses to the existing `missing_lattice` recovery wizard
 * — never a silent fake cell — and **removing** a card before submit must yield a completely
 * ordinary no-repair conversion (the additive invariant at the pixel level).
 */

/** Drive the browser from the landing page to the idle Convert tab of an uploaded fixture. */
async function uploadToConvertTab(page: Page, file: string) {
  await page.goto("/");
  await page.getByRole("link", { name: "Convert a file" }).click();
  await page.getByLabel("Choose a file to convert").setInputFiles(fixturePath(file));
  await page.waitForURL("**/f/**");
  // The workspace's Inspect tab, the pre-existing surface — the repair UI must not appear here.
  await expect(page.getByText(/Detected/i)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("link", { name: "Convert →" }).click();
  await expect(page.getByTestId("repair-picker")).toBeVisible();
}

/** Add a `wrap_into_cell` repair card (the picker's default operation — no parameters needed). */
async function addWrapCard(page: Page) {
  await page.getByTestId("repair-add").click();
  await expect(page.getByTestId("repair-card")).toHaveCount(1);
}

// The cell-less wrap seeds an `awaiting_recovery` pause (a non-terminal job holding one of the
// stack's `max_concurrent_jobs` slots) and never resolves it — the assertion is only that it paused.
// Free the slot after every test the same way the other pausing specs do (recovery-flagship,
// awaiting-recovery), or the leaked seed saturates the cap and starves a later spec's inspect with
// `TOO_MANY_ACTIVE_JOBS` (playwright.config.ts documents the one-seed budget).
let pausedJobId: string | undefined;
test.afterEach(async ({ request }) => {
  if (pausedJobId) {
    await cancelJob(request, pausedJobId);
    pausedJobId = undefined;
  }
});

test("flagship: a wrap_into_cell card converts and the record shows the ⟳ mark, the R5 warning, and Compare before/after", async ({
  page,
}) => {
  await uploadToConvertTab(page, FIXTURES.celledPoscar.file);
  await addWrapCard(page);

  // The only new pre-conversion surface is the repair card — the target picker is unchanged.
  await expect(page.getByRole("heading", { name: "Convert to" })).toBeVisible();

  // Choose Extended XYZ and commit through the B2 confirm step.
  await page.getByRole("button", { name: "Extended XYZ", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to Extended XYZ$/ }).click();
  await expect(page.getByTestId("convert-confirm")).toBeVisible();
  await page.getByRole("button", { name: /^Convert$/ }).click();

  // The job completes; the durable record is one link away.
  await page.waitForURL(/\/f\/[^/]+\/convert/);
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 30_000 });
  await recordLink.click();
  await page.waitForURL(/\/f\/[^/]+\/report\//);

  // (a) The R5 warning reads in plain language on the record — the transformative-loss statement.
  await expect(
    page.getByText(/wrapping discards unwrapped trajectory information/i),
  ).toBeVisible({ timeout: 30_000 });

  // (b) The ⟳ "Modified on request" mark renders for the repair row…
  const repairMark = page.getByRole("img", { name: "Modified on request" });
  await expect(repairMark.first()).toBeVisible();
  // …and it is provably NOT the ◆ violet assumption mark: a transformed coordinate is not a
  // fabricated one, so the class binding is the repair blue, never text-cb-assumption.
  const markClass = await repairMark.first().getAttribute("class");
  expect(markClass).toContain("text-cb-repair");
  expect(markClass).not.toContain("text-cb-assumption");
  // The operation code sits beside the mark in the repair tint.
  await expect(page.getByText("wrap_into_cell", { exact: true }).first()).toBeVisible();

  // (c) The Compare tab renders the two canonical objects side by side — before (source) vs after
  //     (output) — with the repair record on the same page (the report panel always renders below
  //     the viewer tabs, so the ⟳ row is one glance away).
  await page.getByRole("tab", { name: "Compare" }).click();
  const compare = page.locator('section[aria-label="Compare"]');
  await expect(compare.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  await expect(compare.locator("[data-mounted=true]")).toHaveCount(2, { timeout: 60_000 });
  // The source side is unwrapped (atoms may sit outside the box), the output wrapped — the
  // report row that says so is on this same page, below the viewer tabs.
  await repairMark.first().scrollIntoViewIfNeeded();
  await expect(repairMark.first()).toBeVisible();
});

test("a cell-less wrap cannot fabricate a box — it pauses to the existing missing_lattice recovery wizard", async ({
  page,
}) => {
  await uploadToConvertTab(page, FIXTURES.noCellXyz.file);
  await addWrapCard(page);

  // Plain XYZ is the natural target for a cell-less water molecule.
  await page.getByRole("button", { name: "Plain XYZ", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to Plain XYZ$/ }).click();
  await page.getByRole("button", { name: /^Convert$/ }).click();

  // The repair blocks (the wrap needs a lattice to wrap into) and the job pauses to the wizard
  // the page already has — named honestly, never a fabricated box.
  await page.waitForURL(/\/f\/[^/]+\/convert/);
  // Record the paused job so the afterEach frees its `max_concurrent_jobs` slot (it never resolves).
  pausedJobId = new URL(page.url()).searchParams.get("job") ?? undefined;
  await expect(
    page.getByRole("heading", { name: /needs \d+ decisions? before it can proceed/i }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "No simulation cell" })).toBeVisible();
  await expect(page.getByText("missing_lattice", { exact: true })).toBeVisible();
});

test("removing the repair card before submit yields a completely ordinary no-repair conversion", async ({
  page,
}) => {
  await uploadToConvertTab(page, FIXTURES.celledPoscar.file);
  await addWrapCard(page);
  // The card is user-added and removable — removing it returns the request to the pre-v1.7 shape.
  await page.getByTestId("repair-remove").click();
  await expect(page.getByTestId("repair-card")).toHaveCount(0);

  await page.getByRole("button", { name: "Extended XYZ", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to Extended XYZ$/ }).click();
  await page.getByRole("button", { name: /^Convert$/ }).click();

  await page.waitForURL(/\/f\/[^/]+\/convert/);
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 30_000 });
  await recordLink.click();
  await page.waitForURL(/\/f\/[^/]+\/report\//);

  // No repair vocabulary anywhere: no ⟳ mark, no wrap warning, no "Modified on request".
  await expect(page.getByRole("img", { name: "Modified on request" })).toHaveCount(0);
  await expect(page.getByText(/wrapping discards unwrapped trajectory information/i)).toHaveCount(0);
});