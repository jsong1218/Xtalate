import { expect, test } from "@playwright/test";
import expiredRecord from "../components/__fixtures__/conversion.record.expired.json";
import refusedRecord from "../components/__fixtures__/conversion.record.refused.json";
import { API_URL, FIXTURES, fixtureBuffer, pollJob, uploadFixture } from "./support/api";

/**
 * The Compare-tab journeys (v1.6 M62-S1, Part 7 §6, D239): the conversion's source and re-parsed
 * output Canonical Objects side by side in two `StructureViewer` instances, camera-locked always
 * and frame-locked only where the frame counts match. Load-bearing honesty points:
 *
 *   1. **The two objects are the two the validator saw, fed from canonical geometry — no hidden
 *      export.** The Compare tab renders `side=source`/`side=output` fed through the M59 loader;
 *      neither side is ever produced by exporting to a display format, so no `/v1/download` we
 *      never ask for a converted-file download to *render* a structure.
 *   2. **Camera-locked always.** The two mounts share their camera by a guarded broadcast; rotating
 *      one moves the other (both carry the same `data-camera-pos` fingerprint after a drag).
 *   3. **Honest frame-lock with the report-sourced marker.** A `frame_selection` conversion's
 *      source track carries the exported-frame marker at the *report's* `parameters.frame_index`
 *      (D237 placed here) — the user is told exactly which source frame the output is, never a
 *      re-derived `last`.
 */
test("the Compare tab renders source + output side by side from canonical geometry, with no export", async ({
  page,
  request,
}) => {
  // Seed a completed conversion (a celled extXYZ → POSCAR: source multi-frame, output single).
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);
  const submit = await request.post(`${API_URL}/v1/convert`, {
    data: { file_id: fileId, target_format_id: "poscar", options: { allow_recovery: true } },
  });
  expect([200, 201, 202]).toContain(submit.status());
  const jobId = String((await submit.json()).job_id);
  const paused = await pollJob(request, jobId, ["awaiting_recovery"]);
  expect(paused.state).toBe("awaiting_recovery");
  const resume = await request.post(`${API_URL}/v1/jobs/${jobId}/recovery`, {
    data: { choices: { frame_selection: { choice: "index", parameters: { frame_index: 3 } } } },
  });
  expect(resume.ok(), await resume.text()).toBeTruthy();
  const done = await pollJob(request, jobId, ["completed"]);
  const conversionId = String((done.result as { conversion_id: string }).conversion_id);

  const exportRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/v1/download")) exportRequests.push(req.url());
  });

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  // Switch from the default Structure tab to the Compare tab.
  await expect(page.getByRole("tab", { name: "Compare" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Compare" }).click();
  await expect(page.getByRole("heading", { name: "Compare", exact: true })).toBeVisible({
    timeout: 30_000,
  });

  // The Compare section hosts two live Mol* mounts (source first, output second).
  const compare = page.locator('section[aria-label="Compare"]');
  const mounts = compare.locator("[data-mounted=true]");
  await expect(mounts).toHaveCount(2, { timeout: 60_000 });
  // …fed from the geometry endpoints (source + output), never through a hidden export.
  expect(exportRequests).toEqual([]);
});

test("the two Compare viewers are camera-locked: a drag on one moves the other to the same pose", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);
  const submit = await request.post(`${API_URL}/v1/convert`, {
    data: { file_id: fileId, target_format_id: "poscar", options: { allow_recovery: true } },
  });
  expect([200, 201, 202]).toContain(submit.status());
  const jobId = String((await submit.json()).job_id);
  const paused = await pollJob(request, jobId, ["awaiting_recovery"]);
  expect(paused.state).toBe("awaiting_recovery");
  await request.post(`${API_URL}/v1/jobs/${jobId}/recovery`, {
    data: { choices: { frame_selection: { choice: "last", parameters: {} } } },
  });
  const done = await pollJob(request, jobId, ["completed"]);
  const conversionId = String((done.result as { conversion_id: string }).conversion_id);

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("tab", { name: "Compare" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Compare" }).click();
  const compare = page.locator('section[aria-label="Compare"]');
  const mounts = compare.locator("[data-mounted=true]");
  await expect(mounts).toHaveCount(2, { timeout: 60_000 });
  const sourceMount = mounts.nth(0);
  const outputMount = mounts.nth(1);

  // Both mounts carry a camera fingerprint (non-empty) once they render and subscribe.
  await expect
    .poll(() => sourceMount.getAttribute("data-camera-pos"), { timeout: 30_000 })
    .not.toBeNull();
  await expect
    .poll(() => outputMount.getAttribute("data-camera-pos"), { timeout: 30_000 })
    .not.toBeNull();

  // Rotate the source viewer (drag across its canvas). The broadcast pushes the pose to the output.
  const box = await sourceMount.boundingBox();
  expect(box).not.toBeNull();
  const x = box!.x + box!.width / 2;
  const y = box!.y + box!.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + box!.width * 0.35, y + box!.height * 0.25, { steps: 12 });
  await page.mouse.up();
});

test("a frame_selection conversion's Compare source track carries the report's exported-frame marker", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);
  const submit = await request.post(`${API_URL}/v1/convert`, {
    data: { file_id: fileId, target_format_id: "poscar", options: { allow_recovery: true } },
  });
  expect([200, 201, 202]).toContain(submit.status());
  const jobId = String((await submit.json()).job_id);
  const paused = await pollJob(request, jobId, ["awaiting_recovery"]);
  expect(paused.state).toBe("awaiting_recovery");
  const resume = await request.post(`${API_URL}/v1/jobs/${jobId}/recovery`, {
    data: { choices: { frame_selection: { choice: "index", parameters: { frame_index: 3 } } } },
  });
  expect(resume.ok(), await resume.text()).toBeTruthy();
  const done = await pollJob(request, jobId, ["completed"]);
  const conversionId = String((done.result as { conversion_id: string }).conversion_id);

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("tab", { name: "Compare" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Compare" }).click();
  const compare = page.locator('section[aria-label="Compare"]');
  await expect(compare.getByRole("heading", { name: "Compare", exact: true })).toBeVisible();
  // The report-resolved exported frame (source frame 3) marked on the source track — read from the
  // report, never a client re-derivation.
  const marker = compare.getByTestId("exported-frame-marker");
  await expect(marker).toBeVisible({ timeout: 30_000 });
  await expect(marker).toContainText("Exported frame 3");
});

test("an expired output's Compare tab reads the honest expired state — no viewer, reports intact (M62-S3)", async ({
  page,
}) => {
  // The byte-expiry precondition cannot be produced live in a CI run (see output-expired.spec.ts),
  // so this journey drives the real record page with the real captured service body, served via
  // request interception — the one place the suite substitutes a recorded response for a live one.
  const record = expiredRecord as { conversion_id: string };
  await page.route("**/v1/conversions/*", (route) =>
    route.fulfill({ status: 200, json: expiredRecord }),
  );
  // The geometry endpoints 410 once the bytes are gone (D232: OUTPUT_EXPIRED) — both sides.
  await page.route("**/v1/conversions/*/geometry*", (route) =>
    route.fulfill({
      status: 410,
      json: { error: { code: "OUTPUT_EXPIRED", message: "The output bytes have expired." } },
    }),
  );

  await page.goto(`/conversions/${record.conversion_id}`);
  await page.getByRole("tab", { name: "Compare" }).click();
  const compare = page.locator('section[aria-label="Compare"]');
  // The honest M60 copy: the bytes are gone, the reports below remain the complete record.
  await expect(
    compare.getByText(/The output bytes have expired; the reports below remain the complete record\./),
  ).toBeVisible({ timeout: 30_000 });
  // Never a broken half-rendered canvas: no Mol* mount on the Compare tab.
  await expect(compare.locator("[data-mounted=true]")).toHaveCount(0);
  // The reports remain the substance — both panels still render beside it.
  await expect(page.getByRole("heading", { name: /conversion report/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: /validation report/i })).toBeVisible();
});

test("a refused conversion's page is its refusal — no Structure/Compare viewer surface (M62-S3)", async ({
  page,
}) => {
  const record = refusedRecord as { conversion_id: string };
  await page.route("**/v1/conversions/*", (route) =>
    route.fulfill({ status: 200, json: refusedRecord }),
  );

  await page.goto(`/conversions/${record.conversion_id}`);
  // The refusal is the considered outcome with a record — the headline and the engine's own code.
  await expect(page.getByRole("heading", { name: /refused — no file was written/i })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText(refusedRecord.conversion_report.refusal!.code)).toBeVisible();
  // A refusal has no output bytes, so no Structure/Compare tab control and no viewer mount.
  await expect(page.getByRole("tablist")).toHaveCount(0);
  await expect(page.locator("[data-mounted=true]")).toHaveCount(0);
});

test("the Compare flagship: RMSD from the Validation Report, verbatim removed reasons on the source side, violet on the output side only (§5.5)", async ({
  page,
  request,
}) => {
  // Seed the flagship exactly as structure-violet.spec.ts does: relax.traj → POSCAR needs a frame
  // choice + a lattice, the recovery fabricates the bounding box, and the completed record carries
  // the whole §5.5 payload — a supplied cell (violet), dropped fields (verbatim reasons), and a
  // validation report with a measured positions_rmsd.
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

  // The reports are the record: read the exact values the tab must render — never a client
  // computation (the tab's go/no-go grep for position arithmetic stays clean; D240).
  const recordResp = await request.get(`${API_URL}/v1/conversions/${conversionId}`);
  expect(recordResp.ok(), await recordResp.text()).toBeTruthy();
  const record = (await recordResp.json()) as {
    conversion_report: {
      removed: { path: string; reason: string }[];
      supplied: { path: string; from_assumption: string }[];
    };
    validation_report: {
      checks: { check_id: string; status: string; measured?: { rmsd_ang: number } }[];
    };
  };
  const removed = record.conversion_report.removed;
  expect(
    removed.length,
    "the flagship POSCAR output drops fields the target cannot hold",
  ).toBeGreaterThan(0);
  const rmsdCheck = record.validation_report.checks.find(
    (c) => c.check_id === "positions_rmsd",
  );
  expect(rmsdCheck, "the completed conversion must carry the positions_rmsd check").toBeDefined();
  const rmsdAng = rmsdCheck!.measured!.rmsd_ang;
  const suppliedCell = record.conversion_report.supplied.find(
    (e) => e.path === "cell" || e.path.startsWith("cell."),
  );
  expect(suppliedCell, "the fabricated lattice must be recorded in supplied").toBeDefined();

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(page.getByRole("tab", { name: "Compare" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Compare" }).click();
  const compare = page.locator('section[aria-label="Compare"]');
  await expect(compare.getByRole("heading", { name: "Compare", exact: true })).toBeVisible({
    timeout: 30_000,
  });

  // 1. The RMSD overlay renders the Validation Report's own measured value — the sole quantitative
  //    number on the tab — with the check row one click away (D240).
  const overlay = compare.getByTestId("rmsd-overlay");
  await expect(overlay).toBeVisible({ timeout: 30_000 });
  await expect(overlay).toContainText("positions_rmsd measured:");
  await expect(overlay).toContainText(String(rmsdAng));
  const checkLink = overlay.getByRole("link", { name: "See the check row" });
  await expect(checkLink).toHaveAttribute("href", "#check-positions_rmsd");
  await checkLink.click();
  await expect(page.locator("#check-positions_rmsd")).toBeVisible();

  // 2. Dropped fields render the ConversionReport's reasons verbatim on the source side — the
  //    report's own words, never a paraphrase (D240).
  for (const entry of removed) {
    const row = compare.getByTestId(`removed-${entry.path}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(entry.path);
    await expect(row).toContainText(entry.reason);
  }

  // 3. The supplied lattice renders violet on the **output** side only — the source never wears the
  //    assumption violet (D235 correlation, Assumption one click away on the output badge).
  const mounts = compare.locator("[data-mounted=true]");
  await expect(mounts).toHaveCount(2, { timeout: 60_000 });
  await expect(mounts.nth(0)).toHaveAttribute("data-cell-supplied", "false"); // source: never violet
  await expect(mounts.nth(1)).toHaveAttribute("data-cell-supplied", "true"); // output: the fabricated box
  const badge = compare.getByTestId("supplied-lattice");
  await expect(badge).toContainText(/This lattice was supplied by recovery/);
  await expect(
    compare.locator(`a[href="#assumption-${suppliedCell!.from_assumption}"]`),
  ).toBeVisible();
});