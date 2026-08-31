import { expect, test } from "@playwright/test";
import { cancelJob, seedRefusedConversion } from "./support/api";

/**
 * Resolve-and-retry from a refused record (MASTER_SPEC Part 7; IMPLEMENTATION_PLAN_v0.7 M32
 * deliverable 4b; slice M32-S2). A `RECOVERY_REQUIRED` refusal is history the product never rewrites
 * — but it is also no longer a dead-end. From the refused record, with the source upload still in
 * hand, "resolve and retry" re-submits the **same file and target** *with* interactive recovery, so
 * the very scenarios that were unresolved come back as M31 decision cards, and the human drives them
 * to a completed record:
 *
 *     refused record → resolve and retry → PAUSE → decide (last + bounding_box/5) → completed record
 *
 * The refused row is immutable: this creates new history (a fresh convert job), it never edits the
 * old record. Seeding the refusal over the API is the honest path — the UI always submits
 * `allow_recovery: true` now, so a refusal is unreachable by clicking (it would pause instead).
 */

// The retry creates a fresh paused job while the cards are open; if an assertion fails before the
// confirm, that non-terminal job holds a concurrency slot. Free it so repeated runs don't saturate
// `max_concurrent_jobs` (see `cancelJob`).
let retryJobId: string | undefined;
test.afterEach(async ({ request }) => {
  if (retryJobId) {
    await cancelJob(request, retryJobId);
    retryJobId = undefined;
  }
});

test("a refused record resolves and retries through the cards to a completed conversion", async ({
  page,
  request,
}) => {
  // 1. Seed a refused conversion; open its durable record in the workspace (the Report tab — the
  //    refusal is rendered as a considered outcome, not an error).
  const { conversionId, fileId } = await seedRefusedConversion(request);
  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("heading", { name: /refused — no file was written/i })).toBeVisible({
    timeout: 30_000,
  });
  // The refusal names the decisions it needs — the same ones the retry will surface as cards.
  await expect(page.getByTestId("unresolved-scenario").filter({ hasText: "missing_lattice" })).toBeVisible();

  // 2. Resolve and retry — a fresh convert submission for the same file and target.
  await page.getByRole("button", { name: /resolve and retry/i }).click();

  // 3. It routes to a new live job that pauses on the recovery step: one card per unresolved scenario.
  await page.waitForURL("**/convert?**");
  retryJobId = new URL(page.url()).searchParams.get("job") ?? undefined;
  await expect(
    page.getByRole("heading", { name: /needs \d+ decisions? before it can proceed/i }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("decision-card")).toHaveCount(2);

  // 4. Decide both, exactly as the flagship does: the last frame, an axis-aligned bounding box + 5 Å.
  await page.getByRole("radio", { name: /Keep the last frame/ }).check();
  await page.getByRole("radio", { name: /Build a box around the atoms/ }).check();
  await page.getByLabel(/padding_ang/).fill("5");

  // 5. Confirm → the job resumes and completes; the durable record is one link away.
  await page.getByRole("button", { name: /confirm and convert/i }).click();
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 30_000 });
  retryJobId = undefined; // The retry job is terminal now; nothing to clean up.
  await recordLink.click();

  // 6. A completed record this time — a different conversion from the refused one (new history), with
  //    the fabrications recorded and a file to take.
  await page.waitForURL("**/f/*/report/**");
  expect(page.url()).not.toContain(conversionId);
  await expect(page.getByText(/conversion artifact, not simulation data/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Download / })).toBeVisible();
});
