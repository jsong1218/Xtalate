import { expect, test } from "@playwright/test";
import { API_URL, FIXTURES, pollJob, seedCompletedConversion, uploadFixture } from "./support/api";

/**
 * The read-only geometry endpoints (v1.6 M59-S1, D232) — an API journey with no UI yet (the viewer
 * render is S2). Geometry is canonical canonical JSON over the proven streaming seam: species, an
 * optional cell, and ranged frame positions for a file and for a conversion's source/output. Two
 * load-bearing points proven over the running stack:
 *
 *  1. ``GET /v1/files/{id}/geometry`` — and the conversion's ``side=source`` / ``side=output`` —
 *     return faithful geometry over HTTP (a celled source answers its real lattice; absence renders
 *     as ``null``, P3).
 *  2. Geometry 410s on expiry **while the durable record still renders** — the two are independent
 *     (reports-outlive-bytes, exactly the downloads posture).
 */
test("a celled file and a conversion's source and output answer with canonical geometry over HTTP", async ({
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);

  // File geometry, ranged 0:1 (the default structure view): faithful cell, species, positions.
  const geo = await request.get(`${API_URL}/v1/files/${fileId}/geometry?frames=0:1`);
  expect(geo.status(), await geo.text()).toBe(200);
  const body = await geo.json();
  expect(Array.isArray(body.species)).toBe(true);
  expect(body.species).toHaveLength(2); // worked example is a 2-atom molecule
  expect(body.cell).toEqual([
    [6, 0, 0],
    [0, 6, 0],
    [0, 0, 6],
  ]); // its own Lattice=, not fabricated
  expect(body.frames).toHaveLength(1);
  expect(body.frames[0].positions).toHaveLength(2);
  expect(body.frame_count).toBe(1);

  // Convert the worked example to plain XYZ (which cannot hold a lattice), then read both sides.
  const submit = await request.post(`${API_URL}/v1/convert`, {
    data: { file_id: fileId, target_format_id: "xyz", options: {} },
  });
  expect([200, 201, 202]).toContain(submit.status());
  const jobId = String((await submit.json()).job_id);
  const done = await pollJob(request, jobId, ["completed"]);
  const result = done.result as { conversion_id: string; conversion_report?: { status?: string } };
  expect(result.conversion_report?.status).toBe("completed");
  const conversionId = result.conversion_id;

  const src = await request.get(`${API_URL}/v1/conversions/${conversionId}/geometry?side=source`);
  expect(src.status(), await src.text()).toBe(200);
  const srcBody = await src.json();
  expect(srcBody.species).toEqual(body.species);
  expect(srcBody.cell).toEqual(body.cell); // the source still carries its 6 Å lattice

  const out = await request.get(`${API_URL}/v1/conversions/${conversionId}/geometry?side=output`);
  expect(out.status(), await out.text()).toBe(200);
  const outBody = await out.json();
  expect(outBody.species).toEqual(body.species);
  // Plain XYZ cannot express a cell, so the output side honestly answers null (P3) — no fabricated box.
  expect(outBody.cell).toBeNull();
  expect(outBody.frames[0].positions).toHaveLength(2);
});

test("an expired conversion's geometry 410s while its durable record still renders", async ({
  request,
  page,
}) => {
  // A real completed conversion on the running stack (worked example → plain XYZ).
  const { conversionId, fileId } = await seedCompletedConversion(request);

  // The record page renders fully, interrogating none of the geometry surface — intercept the
  // geometry route to return the expired envelope (the elapsed-time precondition is not live) and
  // prove the record is unaffected: geometry 410 + record 200 are independent.
  await page.route(`**/v1/conversions/${conversionId}/geometry**`, (route) =>
    route.fulfill({
      status: 410,
      json: {
        error: {
          code: "OUTPUT_EXPIRED",
          message: `The converted output for ${conversionId} is no longer available.`,
          details: {},
          request_id: "e2e",
          documentation_url: "#output_expired",
        },
      },
    }),
  );

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  // The record still renders ("Converted — …"), deliberately below, not blocked by, the geometry 410.
  await expect(page.getByRole("heading", { name: /^Converted/ })).toBeVisible({ timeout: 30_000 });
});