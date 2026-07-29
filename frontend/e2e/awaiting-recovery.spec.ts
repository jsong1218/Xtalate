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
 * Negative journey — the `awaiting_recovery` pause (MASTER_SPEC Part 6 §3.2, Part 7 §2.4; slices
 * M30-S1, M31-S2). Converting a multi-frame trajectory to single-frame POSCAR needs a decision the
 * file does not contain, so the engine pauses rather than inventing one. As of M31 the page renders
 * that pause as the interactive **recovery step**: named, with one decision card per unresolved
 * scenario, the deadline stated as a refusal-not-a-default, and a first-class decline. The job is
 * seeded over the API, then the browser drives the live job page that long-polls it. The full flow
 * — driving the cards to a completed record — is the M31-S3 flagship spec; this asserts the step
 * appears honestly, never as a silent default.
 */
test("the awaiting_recovery pause is rendered honestly, never as a silent default", async ({
  page,
  request,
}) => {
  const jobId = await seedAwaitingRecoveryJob(request);
  seededJobId = jobId;

  await page.goto(`/convert/${jobId}`);

  // Named, not hidden — the framing sentence with the machine state one glance away.
  await expect(
    page.getByRole("heading", { name: /needs \d+ decisions? before it can proceed/i }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("awaiting_recovery", { exact: true })).toBeVisible();

  // The frame-selection decision this concrete conversion raised is shown as its own decision card.
  await expect(page.getByTestId("decision-card").first()).toBeVisible();
  await expect(page.getByText("frame_selection", { exact: true })).toBeVisible();

  // The deadline is stated as what it is: expiry refuses, it does not choose on the user's behalf.
  await expect(page.getByTestId("recovery-deadline")).toContainText(/refused/i);

  // Decline is first-class — a way out that never traps the user between deciding and leaving.
  await expect(page.getByRole("button", { name: /cancel conversion/i })).toBeVisible();
});
