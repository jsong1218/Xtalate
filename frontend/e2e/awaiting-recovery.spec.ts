import { expect, test } from "@playwright/test";
import { cancelJob, seedAwaitingRecoveryJob } from "./support/api";

// The seeded pause is a non-terminal job holding a concurrency slot; free it after the assertions so
// repeated runs against a persistent stack don't saturate `max_concurrent_jobs` (see `cancelJob`).
let seededJobId: string | undefined;
test.afterEach(async ({ request }) => {
  if (seededJobId) {
    await cancelJob(request, seededJobId);
    seededJobId = undefined;
  }
});

/**
 * Negative journey — the `awaiting_recovery` pause (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slice
 * M30-S1). Converting a multi-frame trajectory to single-frame POSCAR needs a decision the file does
 * not contain, so the engine pauses rather than inventing one. v0.6 has no interactive recovery
 * cards yet, so the page's job is to render that pause *honestly*: named, with the deadline stated
 * as a refusal-not-a-default, and with a real way forward. The job is seeded over the API (the
 * convert button does not ask for interactive recovery yet — see the support helper), then the
 * browser drives the live job page that long-polls it.
 */
test("the awaiting_recovery pause is rendered honestly, never as a silent default", async ({
  page,
  request,
}) => {
  const jobId = await seedAwaitingRecoveryJob(request);
  seededJobId = jobId;

  await page.goto(`/convert/${jobId}`);

  // Named, not hidden — the human sentence with the machine state one glance away.
  await expect(
    page.getByRole("heading", { name: /This conversion needs a decision from you/i }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("awaiting_recovery", { exact: true })).toBeVisible();

  // The frame-selection decision this concrete conversion raised is shown as a scenario.
  await expect(page.getByTestId("awaiting-scenario").first()).toBeVisible();
  await expect(page.getByText("frame_selection", { exact: true })).toBeVisible();

  // The deadline is stated as what it is: expiry refuses, it does not choose on the user's behalf.
  await expect(page.getByTestId("recovery-deadline")).toContainText(/refused/i);
});
