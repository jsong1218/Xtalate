import { expect, test } from "@playwright/test";
import { API_URL, cancelJob, FIXTURES, pollJob, uploadFixture } from "./support/api";

/**
 * The Web UI batch record journey (MASTER_SPEC Part 7 §2.4; v1.5 M58-S2). The API contract is
 * proven by `batch.spec.ts`; this spec drives the **record** through a real browser: a batch
 * parent renders as parent tallies plus links that resolve to the ordinary per-file child
 * records the existing convert page already renders — navigable, not novel — and a paused child's
 * `awaiting_recovery` is visible on that child's own record, where its decision is made.
 *
 * The batch is submitted over the API (there is deliberately no batch-creation UI — the record
 * is navigable, not novel); everything asserted after that is UI. Each test seeds a non-terminal
 * paused job at most briefly, and the `afterEach` cancels it so repeated runs against a
 * persistent stack don't saturate `max_concurrent_jobs`.
 */

interface BatchEnvelope {
  job_id: string;
  state: string;
  children: { job_id: string; file_id: string; state: string }[];
  result?: {
    tallies?: Record<string, unknown>;
    entries?: { child_job_id: string; file_id: string }[];
  };
  [key: string]: unknown;
}

let seededParentId: string | undefined;
let seededChildId: string | undefined;

test.afterEach(async ({ request }) => {
  if (seededChildId) {
    await cancelJob(request, seededChildId);
    seededChildId = undefined;
  }
  if (seededParentId) {
    await cancelJob(request, seededParentId);
    seededParentId = undefined;
  }
});

test("the batch record shows parent tallies and links into each child conversion record", async ({
  page,
  request,
}) => {
  // A two-file batch: one clean conversion (worked-example → POSCAR) and one refusal (the
  // relaxation trajectory → POSCAR needs a frame decision; no preset, so it refuses rather than
  // pausing). The parent completes with honest tallies: 1 converted, 1 refused.
  const clean = await uploadFixture(request, FIXTURES.workedExample);
  const refusing = await uploadFixture(request, FIXTURES.relaxTraj);
  const submit = await request.post(`${API_URL}/v1/batch/convert`, {
    data: { file_ids: [clean, refusing], target_format_id: "poscar", options: {} },
  });
  expect(submit.status(), await submit.text()).toBe(202);
  const parent = (await submit.json()) as BatchEnvelope;

  const done = (await pollJob(request, parent.job_id, ["completed"])) as BatchEnvelope;
  expect(done.state).toBe("completed");
  const entries = done.result!.entries!;
  expect(entries).toHaveLength(2);

  // The batch record: the parent's own page names the batch and renders the service's tallies.
  await page.goto(`/convert/${parent.job_id}`);
  await expect(page.getByRole("heading", { name: "Batch conversion" })).toBeVisible();
  const tallies = page.getByRole("region", { name: "Batch result" });
  await expect(tallies).toContainText("Total");
  await expect(tallies).toContainText("2");
  await expect(tallies).toContainText("Converted");
  await expect(tallies).toContainText("1");
  await expect(tallies).toContainText("Refused");

  // Per-file links resolve to the ordinary child records, in manifest order — each on its own
  // file's workspace Convert tab (UI redesign S2).
  const links = page.getByRole("link", { name: /view this file\u2019s conversion record/i });
  await expect(links).toHaveCount(2);
  await expect(links.first()).toHaveAttribute(
    "href",
    `/f/${entries[0].file_id}/convert?job=${entries[0].child_job_id}`,
  );

  // Follow the converted child's link: the ordinary conversion record renders in its workspace.
  await links.first().click();
  await page.waitForURL(new RegExp(`/f/${entries[0].file_id}/convert\\?job=${entries[0].child_job_id}`));
  await expect(page.getByRole("heading", { name: "Conversion", exact: true })).toBeVisible();
  // The child's durable record — where the download lives — is one link away.
  await expect(
    page.getByRole("link", { name: /view the full record and download the file/i }),
  ).toBeVisible();
});

test("a paused child's awaiting_recovery is visible on its own record, reached from the batch", async ({
  page,
  request,
}) => {
  // relax.traj → POSCAR needs a frame decision; with recovery allowed the child pauses, and the
  // batch honestly waits on it — the batch itself made no choice.
  const traj = await uploadFixture(request, FIXTURES.relaxTraj);
  const submit = await request.post(`${API_URL}/v1/batch/convert`, {
    data: {
      file_ids: [traj],
      target_format_id: "poscar",
      options: { allow_recovery: true },
    },
  });
  expect(submit.status(), await submit.text()).toBe(202);
  const parent = (await submit.json()) as BatchEnvelope;
  seededParentId = parent.job_id;

  const paused = (await pollJob(request, parent.job_id, ["awaiting_recovery"])) as BatchEnvelope;
  const child = paused.children[0];
  expect(child.state).toBe("awaiting_recovery");
  seededChildId = child.job_id;

  // The parent's record names the wait honestly and points at the child's own record.
  await page.goto(`/convert/${parent.job_id}`);
  const card = page.getByRole("region", { name: "Waiting on a decision" });
  await expect(card).toContainText(/made no choice for any file/i);
  const answer = page.getByRole("link", { name: /answer on this conversion's record/i });
  await expect(answer).toHaveAttribute("href", `/f/${child.file_id}/convert?job=${child.job_id}`);

  // The child's own record shows the interactive recovery step — the decision lives there, never
  // on the batch.
  await answer.click();
  await page.waitForURL(new RegExp(`/f/${child.file_id}/convert\\?job=${child.job_id}`));
  await expect(page.getByTestId("recovery-step")).toBeVisible();
});
