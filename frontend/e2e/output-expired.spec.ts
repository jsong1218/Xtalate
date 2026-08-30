import { expect, test } from "@playwright/test";
import expiredRecord from "../components/__fixtures__/conversion.record.expired.json";

/**
 * Negative journey — expired output bytes (MASTER_SPEC Part 6 §4.3, Part 7 §2.6; slice M30-S1).
 *
 * Output bytes are kept only for a byte-lifecycle window (30 minutes on the hosted instance; a day
 * in the compose stack), after which they are gone but the **record is not** — reports outlive
 * bytes. The honest state is a record page that reads *expired*, not *not found*, and says the
 * reports remain fully auditable.
 *
 * This one state cannot be produced live without either waiting out the retention window or setting
 * it to zero stack-wide — which would break every other journey's download in the same stack. So
 * this journey drives the real record page with the **real captured service body** for an expired
 * conversion (the same fixture the component tests assert against), served via request interception.
 * It is the one place the suite substitutes a recorded response for a live one, and only because the
 * elapsed-time precondition is not reproducible in a CI run.
 */
test("an expired output reads as expired, with the record surviving", async ({ page }) => {
  const record = expiredRecord as { conversion_id: string };

  // Narrowed to the record itself (`*`, no `/`): the Structure tab's geometry request (M60) must
  // not receive the record body — the tab renders its own honest state from the live endpoint.
  await page.route("**/v1/conversions/*", (route) =>
    route.fulfill({ status: 200, json: expiredRecord }),
  );

  await page.goto(`/conversions/${record.conversion_id}`);

  // Expired, not "not found": the bytes are gone but the page says so in those words…
  await expect(page.getByText(/The converted file has expired/i)).toBeVisible({ timeout: 30_000 });
  // …and it makes the reports-outlive-bytes promise explicit rather than leaving a broken link.
  await expect(page.getByText(/The record itself has not expired/i)).toBeVisible();
});
