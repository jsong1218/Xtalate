import { expect, test } from "@playwright/test";
import { seedCompletedConversion } from "./support/api";

/**
 * The history page, end to end against the compose stack (MASTER_SPEC Part 7 §2.6; slice M33-S2).
 *
 * A component test proves the table renders whatever `/v1/history` returns; only the running stack
 * proves the milestone's "Done means" — *a user deletes an uploaded file from history and its
 * conversion report remains readable*. So this seeds a real completed conversion (its own newest
 * row), deletes its source file through the page, and asserts the report is still one click away.
 * That is reports-outlive-bytes, exercised through the real backend, worker, and store.
 */
test("deletes a source file from history and keeps its report readable", async ({
  page,
  request,
}) => {
  const { conversionId } = await seedCompletedConversion(request);

  await page.goto("/history");
  await expect(page.getByRole("heading", { level: 1, name: "History" })).toBeVisible();

  // Our seeded conversion is the newest row; find it by its durable record link.
  const row = page.getByTestId(`history-row-${conversionId}`);
  await expect(row).toBeVisible();

  // Loss is visible even at row granularity — XYZ drops the extras the extXYZ carried.
  await expect(row.getByText(/fields removed/)).toBeVisible();

  // The record (report) is reachable, and while the upload is live so are re-convert and delete.
  const openRecord = row.getByRole("link", { name: /open record/i });
  await expect(openRecord).toHaveAttribute("href", `/conversions/${conversionId}`);
  await expect(row.getByRole("link", { name: /re-?convert/i })).toBeVisible();

  // Delete the source file, behind a confirmation that names the retention policy.
  await row.getByRole("button", { name: /delete file/i }).click();
  await expect(row.getByText(/report stays readable/i)).toBeVisible();
  await row.getByRole("button", { name: /^delete$/i }).click();

  // The upload is gone: re-convert and delete fall away, with a stated reason — not a dead button.
  await expect(row.getByText(/source file expired/i)).toBeVisible();
  await expect(row.getByRole("link", { name: /re-?convert/i })).toHaveCount(0);

  // But the report outlives the bytes — open-record still resolves to a readable record.
  await expect(row.getByRole("link", { name: /open record/i })).toBeVisible();
  await row.getByRole("link", { name: /open record/i }).click();
  await expect(page).toHaveURL(new RegExp(`/conversions/${conversionId}$`));
  await expect(page.getByTestId("summary-chips")).toBeVisible();
});
