import { expect, test } from "@playwright/test";
import { API_URL, cancelJob, FIXTURES, pollJob, uploadFixture } from "./support/api";

/**
 * The `batch_convert` API journey (MASTER_SPEC Part 6 §3; v1.5 M58-S1). The Web UI rendering is
 * M58-S2; this spec proves the **API** contract through the real compose stack (Tier 1 worker):
 * a mixed manifest fans out to N ordinary `convert` child jobs and the aggregate result embeds
 * each child's report **verbatim** with the reused library tallies; a child needing an un-preset
 * recovery choice pauses **individually** at `awaiting_recovery` (the batch never answers a
 * recovery question wholesale — the parent stays honestly non-terminal with no block of its own);
 * and once every child is terminal the parent completes on its own poll.
 */

interface BatchEnvelope {
  job_id: string;
  kind: string;
  state: string;
  awaiting_recovery: unknown;
  children: { job_id: string; file_id: string; state: string }[];
  result?: { tallies?: unknown; entries?: unknown };
  [key: string]: unknown;
}

test("a batch fans out to ordinary child jobs and returns a verbatim aggregate", async ({
  request,
}) => {
  // A mixed manifest over the three fixture roles: a clean conversion (worked-example → POSCAR),
  // a refusal (the relaxation trajectory → POSCAR needs a frame decision; no preset, so it
  // refuses rather than pausing), and an unknown format (the Word document). Failure isolation is
  // structural — the unknown child fails and the batch still completes with honest tallies.
  const clean = await uploadFixture(request, FIXTURES.workedExample);
  const refusing = await uploadFixture(request, FIXTURES.relaxTraj);
  const unknown = await uploadFixture(request, FIXTURES.notAStructure);

  const submit = await request.post(`${API_URL}/v1/batch/convert`, {
    data: { file_ids: [clean, refusing, unknown], target_format_id: "poscar", options: {} },
  });
  expect(submit.status(), await submit.text()).toBe(202);
  const parent = (await submit.json()) as BatchEnvelope;
  expect(parent.kind).toBe("batch_convert");

  const done = (await pollJob(request, parent.job_id, ["completed"])) as BatchEnvelope;
  expect(done.state).toBe("completed");
  const result = done.result as {
    tallies: {
      total: number;
      converted: number;
      refused: number;
      failed: number;
      label_presence: { energy: number; forces: number; stress: number };
    };
    entries: {
      file_id: string;
      child_job_id: string;
      status: string;
      conversion_report: { status: string };
      validation_report: unknown;
      error: { code: string } | null;
    }[];
  };
  expect(result.tallies).toEqual({
    total: 3,
    converted: 1,
    refused: 1,
    failed: 1,
    label_presence: { energy: 0, forces: 0, stress: 0 },
  });
  // Entries are in manifest order, each naming its child job.
  expect(result.entries.map((e) => e.file_id)).toEqual([clean, refusing, unknown]);

  const [converted, refused, failed] = result.entries;
  expect(converted.status).toBe("converted");
  expect(converted.conversion_report.status).toBe("completed");
  expect(converted.validation_report).not.toBeNull();
  expect(refused.status).toBe("refused");
  expect(refused.conversion_report.status).toBe("refused");
  expect(failed.status).toBe("failed");
  expect(failed.conversion_report).toBeNull();
  expect(failed.error?.code).toBe("UNKNOWN_FORMAT");

  // The wire contract: children are **ordinary** `convert` jobs by inspection — each child job is
  // independently pollable as its own kind="convert" record.
  for (const entry of result.entries) {
    const child = await pollJob(request, entry.child_job_id, ["completed", "failed"]);
    expect(child.kind).toBe("convert");
  }
});

// A seeded pause is a **non-terminal** job holding a concurrency slot; free it after the
// assertions so repeated runs against a persistent stack don't saturate `max_concurrent_jobs`
// (the awaiting-recovery spec's discipline). We cancel the child (which frees the slot) and then
// the parent, best-effort.
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

test("a child needing recovery pauses individually; the batch completes once it is answered", async ({
  request,
}) => {
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

  // The parent is honestly non-terminal — it carries no block of its own (there is no batch-level
  // question) and the envelope projects its one child so the pause is navigable.
  const pausedParent = (await pollJob(request, parent.job_id, ["awaiting_recovery"])) as BatchEnvelope;
  expect(pausedParent.state).toBe("awaiting_recovery");
  expect(pausedParent.awaiting_recovery).toBeNull();
  expect(pausedParent.children).toHaveLength(1);
  seededChildId = pausedParent.children[0].job_id;
  expect(pausedParent.children[0].state).toBe("awaiting_recovery");

  // The child's own pause is the ordinary one — a real block with the computed option lists.
  const child = await pollJob(request, seededChildId, ["awaiting_recovery"]);
  expect(child.awaiting_recovery).not.toBeNull();

  // Answer the child's own questions — the trajectory→POSCAR pause raised both a frame and a
  // lattice decision (frame_selection + missing_lattice) — never the batch's.
  const resume = await request.post(`${API_URL}/v1/jobs/${seededChildId}/recovery`, {
    data: {
      choices: {
        frame_selection: { choice: "first" },
        missing_lattice: { choice: "bounding_box", parameters: { padding_ang: 5.0 } },
      },
    },
  });
  expect(resume.status(), await resume.text()).toBe(200);

  // Polling the parent re-drives it once every child is terminal: the aggregate now embeds the
  // resumed child's report verbatim.
  const done = (await pollJob(request, parent.job_id, ["completed"])) as BatchEnvelope;
  expect(done.state).toBe("completed");
  const result = done.result as {
    tallies: {
      total: number;
      converted: number;
      refused: number;
      failed: number;
      label_presence: { energy: number; forces: number; stress: number };
    };
    entries: { status: string; conversion_report: { status: string } }[];
  };
  expect(result.tallies).toEqual({
    total: 1,
    converted: 1,
    refused: 0,
    failed: 0,
    label_presence: { energy: 0, forces: 0, stress: 0 },
  });
  expect(result.entries).toHaveLength(1);
  expect(result.entries[0].status).toBe("converted");
  expect(result.entries[0].conversion_report.status).toBe("completed");
});
