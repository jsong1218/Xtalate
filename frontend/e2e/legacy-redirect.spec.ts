import { expect, test } from "@playwright/test";
import { API_URL, seedAwaitingRecoveryJob, seedCompletedConversion } from "./support/api";

/**
 * The no-bookmark-404 rule (UI redesign S2, D244): every pre-workspace URL keeps resolving.
 * The old IA was route-per-surface (`/files/[id]`, `/convert/[job_id]`, `/conversions/[id]`,
 * `/convert`); the new IA is one file-centric workspace (`/f/[file_id]`) with tabs. None of the
 * old paths may 404 — a shared link, a bookmark, or a support thread pointing at one must land on
 * the same content in its new home:
 *
 *     /files/[id]            → /f/[id]                     (server redirect → Inspect tab)
 *     /convert               → /                           (server redirect → landing upload)
 *     /convert/[job_id]      → /f/[id]/convert?job=…       (client redirect, ?file_id= handed forward)
 *     /conversions/[id]      → /f/[id]/report/[id]         (client redirect, ?file_id= or history lookup)
 *
 * The job and conversion records carry no `file_id` on the wire (Part 6 §3.2 / §4.4), so the
 * client redirects resolve the file only when the caller handed it forward or history still maps
 * the record to its live source upload — otherwise the route renders the same content standalone
 * (the reports-outlive-bytes path), which the record journeys in the other specs exercise.
 */
test("every legacy file URL redirects into the file's workspace", async ({ page, request }) => {
  const { conversionId, fileId } = await seedCompletedConversion(request);

  // /files/[id] → the workspace's Inspect tab.
  await page.goto(`/files/${fileId}`);
  await page.waitForURL(`/f/${fileId}`);
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });

  // /convert → the landing, where upload now lives.
  await page.goto("/convert");
  await page.waitForURL("/");
  await expect(page.getByRole("heading", { name: "Convert a file" })).toBeVisible();

  // /conversions/[id] with the file handed forward → the workspace's Report tab.
  await page.goto(`/conversions/${conversionId}?file_id=${encodeURIComponent(fileId)}`);
  await page.waitForURL(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("heading", { name: /^Converted —/ })).toBeVisible({ timeout: 30_000 });
});

test("a bare bookmarked /conversions/[id] resolves the file through history into the Report tab", async ({
  page,
  request,
}) => {
  // No ?file_id=: the redirect must resolve the file from /v1/history (the upload is still live).
  // The page's lookup is one-shot, so first make the precondition durable over the API: the row
  // is listed with its file_id — otherwise the test would race the worker's persistence.
  const { conversionId, fileId } = await seedCompletedConversion(request);
  await expect
    .poll(async () => {
      const resp = await request.get(`${API_URL}/v1/history`);
      expect(resp.ok(), await resp.text()).toBeTruthy();
      const items = (await resp.json()).items as { conversion_id: string; file_id: string | null }[];
      return items.some((i) => i.conversion_id === conversionId && Boolean(i.file_id));
    }, { timeout: 15_000 })
    .toBe(true);

  await page.goto(`/conversions/${conversionId}`);
  await page.waitForURL(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("heading", { name: /^Converted —/ })).toBeVisible({ timeout: 30_000 });
});

test("a bookmarked /convert/[job_id] resolves into the workspace's Convert tab", async ({
  page,
  request,
}) => {
  // A paused job is the honest live case: the URL a caller shares mid-recovery.
  const { jobId, fileId } = await seedAwaitingRecoveryJob(request);

  await page.goto(`/convert/${jobId}?file_id=${encodeURIComponent(fileId)}`);
  await page.waitForURL(`/f/${fileId}/convert?job=${jobId}`);
  await expect(page.getByTestId("recovery-step")).toBeVisible({ timeout: 30_000 });
});
