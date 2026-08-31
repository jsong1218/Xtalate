import { expect, test } from "@playwright/test";
import { API_URL, FIXTURES, fixtureBuffer, pollJob, uploadFixture } from "./support/api";

/**
 * The report-index + exported-frame journeys (v1.6 M61-S2, Part 7 §6 / Part 4 §7, D237).
 *
 * Two load-bearing honesty points for the scrubber:
 *
 *  1. **Frame indices are report indices.** The scrubber's absolute frame numbering is the
 *     DiscoveryReport/ConversionReport frame numbering — scrub to *N*, see frame *N* as the report
 *     names it. Proven on the file page: drive the inspect job for the Discovery Report's own
 *     `structure.frame_count`, then scrub to the last frame and watch the readout name
 *     "N-1 / N" — the report's numbering, not a window-local count.
 *
 *  2. **The exported/selected frame is report-sourced, never re-derived.** A conversion whose
 *     output was produced by a `frame_selection` recovery is a single-frame output — no output-side
 *     track to scrub — so the Structure tab names which source frame it is, read **only** from the
 *     ConversionReport Assumption's `parameters.frame_index` (the engine resolved `index`/`last`/
 *     `first` to the absolute 0-based index), with the Assumption one click away. The annotation
 *     text is the report's own number — the viewer told the user nothing the report didn't.
 */
test("a frame_selection conversion names its source frame from the report, one click away (D237)", async ({
  page,
  request,
}) => {
  // 1. Seed the pause: multi-frame extXYZ → POSCAR needs a frame choice (it carries a cell, so no
  //    lattice recovery). Drive it over the API exactly as the flagship recovery journey does.
  const upload = await request.post(`${API_URL}/v1/upload`, {
    multipart: {
      file: {
        name: FIXTURES.multiFrame.file,
        mimeType: FIXTURES.multiFrame.mimeType,
        buffer: fixtureBuffer(FIXTURES.multiFrame.file),
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

  // 2. Decide: keep the 4th frame (absolute 0-based index 3 — a deliberately non-first/non-last
  //    pick, so the annotation can only come from `parameters.frame_index`, never an edge default).
  const resume = await request.post(`${API_URL}/v1/jobs/${jobId}/recovery`, {
    data: {
      choices: { frame_selection: { choice: "index", parameters: { frame_index: 3 } } },
    },
  });
  expect(resume.ok(), await resume.text()).toBeTruthy();
  const done = await pollJob(request, jobId, ["completed"]);
  const conversionId = String((done.result as { conversion_id: string }).conversion_id);

  // 3. The record's Assumption is the *source* of the annotation — read it, not the geometry.
  const recordResp = await request.get(`${API_URL}/v1/conversions/${conversionId}`);
  expect(recordResp.ok(), await recordResp.text()).toBeTruthy();
  const record = (await recordResp.json()) as {
    conversion_report: {
      assumptions: {
        id: string;
        scenario: string;
        choice: string;
        parameters: { frame_index?: number };
      }[];
    };
  };
  const fs = record.conversion_report.assumptions.find(
    (a) => a.scenario === "frame_selection",
  );
  expect(fs, "the completed conversion must carry the frame_selection Assumption").toBeDefined();
  expect(fs!.parameters.frame_index, "the engine resolved the absolute source index").toBe(3);

  // 4. The browser: the record's Structure tab carries the report-sourced annotation. A single
  //    frame_selection output is one frame → no output-side scrubber, just the annotation.
  await page.goto(`/f/${fileId}/report/${conversionId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  const badge = page.getByTestId("exported-frame");
  await expect(badge).toBeVisible({ timeout: 30_000 });
  await expect(badge).toContainText(
    `This output is source frame ${fs!.parameters.frame_index}`,
  );
  await expect(page.getByRole("slider", { name: "Trajectory frame" })).toHaveCount(0);

  // 5. One click away: the link lands on the Conversion Report panel's own Assumption row.
  const link = page.locator(`a[href="#assumption-${fs!.id}"]`);
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.locator(`#assumption-${fs!.id}`)).toBeVisible();
});

test("the file-page scrubber's frame numbering is the Discovery Report's (report-index identity, D237)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);

  // Drive the inspect job so the *report's own* frame count is the oracle — not the geometry's.
  const insp = await request.post(`${API_URL}/v1/inspect`, { data: { file_id: fileId } });
  expect([200, 201, 202]).toContain(insp.status());
  const inspJobId = String((await insp.json()).job_id);
  const inspDone = await pollJob(request, inspJobId, ["completed"]);
  const report = (inspDone.result as {
    discovery_report?: { structure?: { frame_count?: number } };
  })?.discovery_report;
  const frameCount = report?.structure?.frame_count;
  expect(frameCount, "the Discovery Report must report a frame count").toBe(6);

  await page.goto(`/f/${fileId}/structure`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });

  // Scrub to the last frame (absolute): `data-current-frame` and the readout name the report's own
  // index and its total — frame indices are report indices, not window-local counts.
  const last = (frameCount as number) - 1;
  await slider.fill(String(last));
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toHaveAttribute("data-current-frame", String(last), { timeout: 30_000 });
  await expect(page.getByRole("status").filter({ hasText: "/" })).toContainText(`${last} / ${frameCount}`);
});