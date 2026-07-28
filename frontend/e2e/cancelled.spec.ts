import { expect, test } from "@playwright/test";
import { seedAwaitingRecoveryJob } from "./support/api";

/**
 * Negative journey — a cancelled job (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slice M30-S1). A paused
 * conversion is a non-terminal job, so the page offers to cancel it; cancelling produces **no
 * report** — not an empty one, none at all — because nothing was written and nothing was measured.
 * The honest state is a card that says exactly that, not a blank report shell. Seeding the pause
 * over the API gives a deterministic non-terminal job to cancel (a fast xyz→xyz job would finish
 * before a click could land).
 */
test("cancelling a paused job shows that no report exists, not an empty one", async ({
  page,
  request,
}) => {
  const jobId = await seedAwaitingRecoveryJob(request);

  await page.goto(`/convert/${jobId}`);

  const cancelButton = page.getByRole("button", { name: /Cancel this conversion/i });
  await expect(cancelButton).toBeVisible({ timeout: 30_000 });
  await cancelButton.click();

  // The re-read job resolves to `cancelled`; the page states plainly that there is no report.
  await expect(page.getByRole("heading", { name: /^Cancelled$/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/no report exists for it/i)).toBeVisible();
});
