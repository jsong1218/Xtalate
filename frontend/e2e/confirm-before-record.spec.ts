import { expect, test, type APIRequestContext } from "@playwright/test";
import { API_URL, fixturePath, FIXTURES } from "./support/api";

/**
 * Confirm before record (v1.1 M39-S4, B2) — the fix for "convert-again records instantly; no exit
 * without converting." With the inline queue a single Convert click runs the whole conversion and
 * writes a **completed** record before the response returns, so an exploratory click commits a
 * history row (completed records belong in History by design — the fix is to not commit exploratory
 * clicks, not to hide records). The chosen behaviour: the first click opens an explicit inline
 * confirm step (the pre-flight preview, with a final Convert and a Cancel), and `POST /v1/convert`
 * fires only on the final Convert — so Cancel leaves no row, and Confirm is what records it.
 *
 * Driven entirely through the browser, with `/v1/history` (the same surface the History page
 * renders) read over the API for the row-count assertion.
 */

async function historyCount(request: APIRequestContext): Promise<number> {
  const resp = await request.get(`${API_URL}/v1/history`);
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return (await resp.json()).items.length;
}

test("Cancel leaves no history row; Confirm is what records the conversion", async ({
  page,
  request,
}) => {
  // 1. Upload the worked example through the UI and inspect it.
  await page.goto("/");
  await page.getByRole("link", { name: "Convert a file" }).click();
  await page.getByLabel("Choose a file to convert").setInputFiles(fixturePath(FIXTURES.workedExample.file));
  await page.waitForURL("**/files/**");
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });

  const before = await historyCount(request);

  // 2. Pick plain XYZ and open the confirm step, then CANCEL. The first click must not submit.
  await page.getByRole("button", { name: "Plain XYZ", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to Plain XYZ$/ }).click();
  await expect(page.getByTestId("convert-confirm")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("convert-confirm")).not.toBeVisible();

  // No POST happened ⇒ no record was written: history has no new row.
  expect(await historyCount(request)).toBe(before);

  // 3. Open the confirm step again and COMMIT with the final Convert. Only now is it recorded.
  await page.getByRole("button", { name: /^Convert to Plain XYZ$/ }).click();
  await expect(page.getByTestId("convert-confirm")).toBeVisible();
  await page.getByRole("button", { name: /^Convert$/ }).click();

  // The job completes and the record appears in history.
  await page.waitForURL("**/convert/**");
  await expect(
    page.getByRole("link", { name: /View the full record and download the file/i }),
  ).toBeVisible({ timeout: 30_000 });
  expect(await historyCount(request)).toBe(before + 1);
});
