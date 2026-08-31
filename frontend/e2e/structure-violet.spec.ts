import { expect, test } from "@playwright/test";
import {
  API_URL,
  cancelJob,
  FIXTURES,
  fixtureBuffer,
  pollJob,
  uploadFixture,
} from "./support/api";

/**
 * The supplied-geometry violet rule in 3D (v1.6 M60-S3, D235) — the milestone's flagship: the
 * `relax.traj → POSCAR` recovery whose output lattice is a **fabricated bounding box** the source
 * never had. On the completed record, the Structure tab renders that lattice in the ◆
 * `text-cb-assumption` violet with its Assumption **one click away** — correlated **from the
 * report** (`conversion_report.supplied[].path` + `from_assumption`), never re-derived from the
 * geometry, and the viewer told the user nothing the report didn't (the version's honesty
 * invariant).
 *
 * The recovery is driven over the API (the pause + choices are the same engine the flagship
 * journey clicks through — `recovery-flagship.spec.ts` proves the browser path); this journey's
 * subject is the violet on the durable record.
 */
test("the flagship bounding-box lattice renders violet with its Assumption one click away", async ({
  page,
  request,
}) => {
  // 1. Seed the pause: relax.traj → POSCAR needs a frame choice + a lattice, so the job pauses.
  const upload = await request.post(`${API_URL}/v1/upload`, {
    multipart: {
      file: {
        name: FIXTURES.relaxTraj.file,
        mimeType: FIXTURES.relaxTraj.mimeType,
        buffer: fixtureBuffer(FIXTURES.relaxTraj.file),
      },
    },
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const fileId = String((await upload.json()).file_id);

  const submit = await request.post(`${API_URL}/v1/convert`, {
    data: { file_id: fileId, target_format_id: "poscar", options: { allow_recovery: true } },
  });
  expect([200, 201, 202]).toContain(submit.status());
  const jobId = String((await submit.json()).job_id);
  const paused = await pollJob(request, jobId, ["awaiting_recovery"]);
  expect(paused.state).toBe("awaiting_recovery");

  // 2. Decide both, exactly as the flagship does: the last frame + an axis-aligned bounding box
  //    with 5 Å of padding. (If the assertions below fail, the job is left paused — free the slot.)
  const resume = await request.post(`${API_URL}/v1/jobs/${jobId}/recovery`, {
    data: {
      choices: {
        frame_selection: { choice: "last", parameters: {} },
        missing_lattice: { choice: "bounding_box", parameters: { padding_ang: 5 } },
      },
    },
  });
  expect(resume.ok(), await resume.text()).toBeTruthy();
  const done = await pollJob(request, jobId, ["completed"]);
  expect(done.state).toBe("completed");
  const conversionId = String((done.result as { conversion_id: string }).conversion_id);

  // 3. Read the durable record's own correlation facts — the report is the source of the violet.
  const recordResp = await request.get(`${API_URL}/v1/conversions/${conversionId}`);
  expect(recordResp.ok(), await recordResp.text()).toBeTruthy();
  const record = (await recordResp.json()) as {
    conversion_report: {
      supplied: { path: string; from_assumption: string }[];
      assumptions: { id: string; description: string }[];
    };
  };
  // The engine records the fabricated lattice on the `cell` canonical family's leaf paths
  // (e.g. `cell.lattice_vectors`, `cell.pbc`) — the wire carries no bare `cell` entry — so match
  // the family, exactly as StructureTab does (D235).
  const suppliedCell = record.conversion_report.supplied.find(
    (e) => e.path === "cell" || e.path.startsWith("cell."),
  );
  expect(suppliedCell, "the fabricated lattice must be recorded in `supplied`").toBeDefined();
  const assumption = record.conversion_report.assumptions.find(
    (a) => a.id === suppliedCell!.from_assumption,
  );
  expect(assumption, "the supplied cell must trace to a recorded Assumption").toBeDefined();
  expect(assumption!.description).toMatch(/axis-aligned bounding box/i);

  // 4. The browser: the record's Structure tab draws the fabricated lattice violet.
  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-has-cell", "true");
  // The violet: the wireframe is drawn in the assumption violet (report-sourced flag).
  await expect(mount).toHaveAttribute("data-cell-supplied", "true");

  // The ◆ violet badge says the fabrication plainly and links to its Assumption one click away;
  // the assumption's full description is surfaced by the report panel's own row, not duplicated.
  const badge = page.getByTestId("supplied-lattice");
  await expect(badge).toBeVisible();
  await expect(badge).toContainText(/This lattice was supplied by recovery/);

  // 5. One click away: the link lands on the Conversion Report panel's own Assumption row.
  const link = page.locator(`a[href="#assumption-${assumption!.id}"]`);
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.locator(`#assumption-${assumption!.id}`)).toBeVisible();
});

test("the files-page tab never renders violet (a discovery record has no supplied)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  await page.goto(`/f/${fileId}/structure`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  // Even though this file's cell renders a wireframe, nothing is supplied — no violet anywhere.
  await expect(mount).toHaveAttribute("data-cell-supplied", "false");
  await expect(page.getByTestId("supplied-lattice")).toHaveCount(0);
});
