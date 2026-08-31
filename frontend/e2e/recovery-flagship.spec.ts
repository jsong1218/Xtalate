import { expect, test } from "@playwright/test";
import { cancelJob, fixturePath, FIXTURES } from "./support/api";

/**
 * The flagship recovery journey (MASTER_SPEC Part 4 §5, Part 7 §3; IMPLEMENTATION_PLAN_v0.7 §5.1;
 * slice M31-S3). This is v0.7's whole reason to exist, driven **entirely in the browser** — no API
 * shortcut for the pause, because as of M31 the convert button submits `allow_recovery: true`, so a
 * conversion that needs a decision pauses on the page instead of refusing (D95, lifted):
 *
 *     upload relax.traj → inspect → convert to POSCAR → PAUSE → decide (last + bounding_box/5)
 *       → preview the exact Assumptions → confirm → record whose report is those Assumptions
 *
 * The source is a 3-frame ASE relaxation trajectory and the target is single-structure POSCAR that
 * also requires a cell — so the engine pauses on two decisions the file cannot answer: which frame
 * survives, and what lattice to write. The human makes both through the cards, sees the **exact**
 * sentences that will be recorded before committing, and lands on a durable record carrying those
 * same sentences verbatim. That byte-for-byte identity between preview and record is the point: the
 * user confirmed the provenance, not a UI approximation of it (P4).
 */

// If an assertion fails before the confirm, the job is left paused — a non-terminal job holding one
// of the stack's `max_concurrent_jobs` slots. Free it so repeated runs don't saturate the cap.
let pausedJobId: string | undefined;
test.afterEach(async ({ request }) => {
  if (pausedJobId) {
    await cancelJob(request, pausedJobId);
    pausedJobId = undefined;
  }
});

test("upload → convert → pause → decide → preview → record, the trajectory→POSCAR flagship", async ({
  page,
}) => {
  // 1. Landing → upload the relaxation trajectory through the UI, exactly as a user would.
  await page.goto("/");
  await page.getByRole("link", { name: "Convert a file" }).click();
  await expect(page.getByRole("heading", { name: "Convert a file" })).toBeVisible();
  await page.getByLabel("Choose a file to convert").setInputFiles(fixturePath(FIXTURES.relaxTraj.file));

  // 2. Inspection routes into the file's workspace (the Inspect tab) and reports what it is.
  await page.waitForURL("**/f/**");
  await expect(page.getByText(/Detected\s+ASE Trajectory/i)).toBeVisible({ timeout: 30_000 });

  // 3. Advance the guided spine with the rail's Convert CTA, choose POSCAR and convert. Permissive
  //    is the default; the difference from v0.6 is that this now asks for interactive recovery, so
  //    the decision-needing conversion pauses rather than refusing. Since v1.1 M39-S4 (B2) the
  //    conversion is committed on an explicit confirm step — and this journey proves the recovery
  //    path is unaffected: confirm → POST → awaiting_recovery → decision cards, exactly as before.
  await page.getByRole("link", { name: "Convert →" }).click();
  await page.getByRole("button", { name: "VASP POSCAR", exact: true }).click();
  await page.getByRole("button", { name: /^Convert to VASP POSCAR$/ }).click();
  await expect(page.getByTestId("convert-confirm")).toBeVisible();
  await page.getByRole("button", { name: /^Convert$/ }).click();

  // 4. The live job on the workspace's Convert tab reaches the pause and renders it as the
  //    recovery step — named, with one card per decision, never a silent default.
  await page.waitForURL(/\/f\/[^/]+\/convert/);
  pausedJobId = new URL(page.url()).searchParams.get("job") ?? undefined;
  await expect(
    page.getByRole("heading", { name: /needs \d+ decisions? before it can proceed/i }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("decision-card")).toHaveCount(2);

  // 5. Decide both. Which frame survives: the last (the converged geometry of a relaxation). What
  //    lattice to write: an axis-aligned bounding box with 5 Å of padding. No option was preselected,
  //    so each of these is a deliberate act.
  await page.getByRole("radio", { name: /Keep the last frame/ }).check();
  await page.getByRole("radio", { name: /Build a box around the atoms/ }).check();
  await page.getByLabel(/padding_ang/).fill("5");

  // 6. With every decision made, the wizard fetches the engine's **exact** Assumption sentences and
  //    shows each on its card. The user confirms these, not a paraphrase — so both must be visible
  //    before confirming, and both name the fabrication honestly (a chosen frame; a cell that is a
  //    conversion artifact, not simulation data).
  await expect(page.getByText(/selected for the single-structure target/i)).toBeVisible();
  await expect(page.getByText(/recorded choice, not a silent default/i)).toBeVisible();
  await expect(page.getByText(/axis-aligned bounding box/i)).toBeVisible();
  await expect(page.getByText(/conversion artifact, not simulation data/i)).toBeVisible();

  // 7. Confirm → the job resumes and runs to completion; the durable record is one link away.
  await page.getByRole("button", { name: /confirm and convert/i }).click();
  const recordLink = page.getByRole("link", { name: /View the full record and download the file/i });
  await expect(recordLink).toBeVisible({ timeout: 30_000 });
  pausedJobId = undefined; // The job is terminal now; nothing to clean up.
  await recordLink.click();

  // 8. The record (the workspace's Report tab) carries the very sentences previewed — byte-for-byte,
  //    because both are the engine's own text. This is the audit trail the whole product exists to
  //    produce.
  await page.waitForURL(/\/f\/[^/]+\/report\//);
  await expect(page.getByText(/selected for the single-structure target/i)).toBeVisible();
  await expect(page.getByText(/conversion artifact, not simulation data/i)).toBeVisible();

  // 9. Only now, below what the conversion cost, is the file offered.
  await expect(page.getByRole("button", { name: /^Download / })).toBeVisible();
});
