import { expect, test } from "@playwright/test";
import { API_URL } from "./support/api";

/**
 * Negative journey — an oversized upload (MASTER_SPEC Part 7 §5 item 4; slice M30-S1). The size gate
 * is the backend's (`_bounded_chunks` rejects mid-stream with `413 FILE_TOO_LARGE`), so this drives
 * the *real* gate rather than a client-side pre-check: it reads the instance's actual ceiling from
 * `GET /v1/limits`, then uploads a file just over it and asserts the service's own envelope renders
 * verbatim in the drop zone. The e2e compose stack runs with a small `XTALATE_MAX_UPLOAD_BYTES` so
 * "just over the limit" is a kilobyte-scale file, not a real 100 MB transfer (see the CI lane).
 */
test("an over-limit upload surfaces the verbatim FILE_TOO_LARGE envelope", async ({ page }) => {
  // Read the ceiling this instance actually advertises, so the test tracks the stack's config.
  const limitsResp = await page.request.get(`${API_URL}/v1/limits`);
  expect(limitsResp.ok(), await limitsResp.text()).toBeTruthy();
  const maxUploadBytes: number = (await limitsResp.json()).max_upload_bytes;

  // A file one comfortable step past the ceiling — enough that the streaming gate trips well before
  // the last byte, regardless of chunk size.
  const oversized = Buffer.alloc(maxUploadBytes + 64 * 1024, 0x41);

  await page.goto("/convert");
  await page.getByLabel("Choose a file to convert").setInputFiles({
    name: "too-big.xyz",
    mimeType: "chemical/x-xyz",
    buffer: oversized,
  });

  await expect(page.getByText("FILE_TOO_LARGE", { exact: true })).toBeVisible({ timeout: 30_000 });

  // Revision 1.4 / D31: the oversize path is a funnel to the free local path, not a dead end.
  await expect(page.getByTestId("size-funnel")).toBeVisible();
});
