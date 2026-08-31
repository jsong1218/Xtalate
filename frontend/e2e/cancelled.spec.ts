import { expect, test } from "@playwright/test";
import { cancelJob, seedAwaitingRecoveryJob } from "./support/api";

// This test cancels its seeded pause through the UI, but a failure before that click would leave the
// non-terminal job holding a concurrency slot — so free it unconditionally too (a no-op once the UI
// has already cancelled it; see `cancelJob`).
let seededJobId: string | undefined;
test.afterEach(async ({ request }) => {
  if (seededJobId) {
    await cancelJob(request, seededJobId);
    seededJobId = undefined;
  }
});

/**
 * Negative journey — a cancelled job (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slices M30-S1, M31-S2).
 * A paused conversion is a non-terminal job, so the page offers to cancel it; cancelling produces
 * **no report** — not an empty one, none at all — because nothing was written and nothing was
 * measured. The honest state is a card that says exactly that, not a blank report shell. Seeding the
 * pause over the API gives a deterministic non-terminal job to cancel (a fast xyz→xyz job would
 * finish before a click could land).
 *
 * As of M31 the paused job's cancel is the recovery step's **first-class decline** — "Cancel
 * conversion", inside the decision surface — not the footer "Cancel this conversion" button, which
 * M31 suppresses while `awaiting_recovery` so there are not two identical controls (see the job
 * page). This spec drives that decline; declining still lands on the same cancelled outcome.
 */
test("cancelling a paused job shows that no report exists, not an empty one", async ({
  page,
  request,
}) => {
  const { jobId, fileId } = await seedAwaitingRecoveryJob(request);
  seededJobId = jobId;

  await page.goto(`/f/${fileId}/convert?job=${jobId}`);

  const cancelButton = page.getByRole("button", { name: /Cancel conversion/i });
  await expect(cancelButton).toBeVisible({ timeout: 30_000 });
  await cancelButton.click();

  // The re-read job resolves to `cancelled`; the page states plainly that there is no report.
  await expect(page.getByRole("heading", { name: /^Cancelled$/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/no report exists for it/i)).toBeVisible();
});
