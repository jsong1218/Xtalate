import { expect, test } from "@playwright/test";
import { API_URL } from "./support/api";

/**
 * Negative journey — an oversized upload (MASTER_SPEC Part 7 §2.2; slices M30-S1, v1.1 M39-S4 A2).
 *
 * As of v1.1 M39-S4 (A2) the drop zone refuses an over-limit file **client-side**, before any bytes
 * leave the browser: with the live ceiling known (`GET /v1/limits`), a file over it never reaches
 * the uploader at all — an upload would only die at the Next proxy as an opaque 500/ECONNRESET (the
 * D112 proxy-ceiling rule), never the backend's honest 413. So this journey asserts the funnel
 * renders **and that no network upload happened**. The backend's 413 stays the backstop for the
 * in-limits window and for when the limit is unknown; the e2e compose stack runs with a small
 * `XTALATE_MAX_UPLOAD_BYTES` so "just over the limit" is a kilobyte-scale file, not a real 100 MB
 * transfer (see the CI lane).
 */
test("an over-limit upload is refused client-side with the funnel and no network upload", async ({
  page,
}) => {
  // Track every attempt to reach the upload endpoint — there must be none.
  const uploadRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/v1/upload")) uploadRequests.push(request.url());
  });

  // Read the ceiling this instance actually advertises, so the test tracks the stack's config.
  const limitsResp = await page.request.get(`${API_URL}/v1/limits`);
  expect(limitsResp.ok(), await limitsResp.text()).toBeTruthy();
  const maxUploadBytes: number = (await limitsResp.json()).max_upload_bytes;

  // A file one comfortable step past the ceiling.
  const oversized = Buffer.alloc(maxUploadBytes + 64 * 1024, 0x41);

  await page.goto("/");
  // A2's pre-check requires the live ceiling to be *known in the browser*: the drop zone renders
  // the limits line only once `max_upload_bytes` has been fetched, so waiting for it here makes
  // the journey deterministically exercise the client-side refusal it asserts — never the
  // server-413 backstop, which renders the same funnel only after bytes have left the browser
  // (a race when the file is chosen before the limits query lands).
  await expect(page.getByText(/on this instance/)).toBeVisible();
  await page.getByLabel("Choose a file to convert").setInputFiles({
    name: "too-big.xyz",
    mimeType: "chemical/x-xyz",
    buffer: oversized,
  });

  // The funnel renders through the same envelope + redirect the server 413 would produce…
  await expect(page.getByText("FILE_TOO_LARGE", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("size-funnel")).toBeVisible();

  // …and nothing was uploaded: the pre-check refused before any bytes left the browser (A2).
  expect(uploadRequests).toHaveLength(0);
});
