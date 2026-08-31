import { expect, test } from "@playwright/test";
import { seedFailedValidationConversion } from "./support/api";

/**
 * The failed-validation acknowledgment gate, end to end against the compose stack (MASTER_SPEC
 * Part 7 §2.5 item 2, Part 5 §2; IMPLEMENTATION_PLAN_v0.7 §5, M32 checkpoint; slice M32-S1).
 *
 * The failure is real, not mocked: a legitimate conversion run under a deliberately tight custom
 * tolerance profile fails its position check on the representational residual alone (see
 * `seedFailedValidationConversion`). So the record the browser lands on carries a genuine
 * `download.requires_ack`, produced by the same worker and validator that serve every user.
 *
 * The journey the gate exists for:
 *
 *     failed-validation record → download is gated, naming the failed checks → acknowledge → the
 *       file downloads → the record still shows the failure
 *
 * The two invariants that must hold in the running stack, not just in jsdom: there is no plain
 * download button to click past the gate, and acknowledging gates *access* without rewriting the
 * record — the failure it reports still stands after the bytes are taken.
 */
test("a failed-validation output cannot be downloaded without passing the acknowledgment gate", async ({
  page,
  request,
}) => {
  const { conversionId, fileId } = await seedFailedValidationConversion(request);

  // Land on the durable record in its workspace, exactly as a user following their conversion would.
  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });

  const download = page.getByTestId("download-panel");
  await expect(download).toBeVisible();

  // 1. The gate states the wall up front and names the failed check by id — sourced from the
  //    record's own Validation rows, in the engine's own words.
  await expect(download.getByText(/validation failed for this output/i)).toBeVisible();
  await expect(download.getByTestId("failed-checks")).toContainText("positions_rmsd");

  // 2. There is no ordinary download button to click past the gate, and the acknowledged download
  //    is disabled until the reader explicitly acknowledges (nothing preselected).
  await expect(download.getByRole("button", { name: /^Download output/i })).toHaveCount(0);
  const ack = download.getByRole("checkbox");
  await expect(ack).not.toBeChecked();
  const takeButton = download.getByRole("button", { name: /download the unverified file/i });
  await expect(takeButton).toBeDisabled();

  // 3. Acknowledge, and only then is the file offered. Capturing the browser download confirms the
  //    service streamed real bytes for the acknowledged request.
  await ack.check();
  await expect(takeButton).toBeEnabled();
  const [saved] = await Promise.all([page.waitForEvent("download"), takeButton.click()]);
  expect(saved.suggestedFilename().length).toBeGreaterThan(0);

  // 4. Acknowledgment gated access; it did not rewrite history. The record still reports the failure.
  await expect(download.getByText(/validation failed for this output/i)).toBeVisible();
});
