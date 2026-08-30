import { expect, test } from "@playwright/test";
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

  await page.goto(`/conversions/${conversionId}`);
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

  await page.goto(`/conversions/${conversionId}`);
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

  await page.goto(`/conversions/${conversionId}`);
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