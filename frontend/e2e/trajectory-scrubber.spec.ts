import { expect, test } from "@playwright/test";
import { API_URL, FIXTURES, pollJob, uploadFixture } from "./support/api";

/**
 * The trajectory scrubber journeys (v1.6 M61-S1, Part 7 §6, D236): a multi-frame object on the
 * Structure tab gains a frame-number scrubber + playback fed by the M59 ranged geometry endpoint,
 * and scrubbing changes what the viewer displays — proven in the browser over the live stack. Four
 * load-bearing points:
 *
 *  1. A multi-frame file shows the scrubber and scrubbing advances the displayed frame
 *     (`data-current-frame` changes — the frame the mount is actually showing).
 *  2. A single-frame file shows **no** scrubber (M60's static render, unchanged).
 *  3. A variable-cell trajectory shows the unit-cell wireframe flip **per displayed frame**
 *     (`data-unitcell-drawn` — a cell-less frame draws no box, P3, at the render level).
 *  4. A conversion with a multi-frame output scrubs on the output side.
 */
test("a multi-frame file's Structure tab scrubs frames, and a single-frame file shows no scrubber", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);

  await page.goto(`/files/${fileId}`);
  await expect(page.getByRole("heading", { name: "Structure", exact: true })).toBeVisible({
    timeout: 30_000,
  });

  // The scrubber appears for a multi-frame object: a frame-number readout and a range control.
  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("status")).toContainText("0 / 6");

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-atoms", "2");
  await expect(mount).toHaveAttribute("data-current-frame", "0");

  // Scrub to frame 5: the displayed frame advances (the mount reports the absolute report index).
  await slider.fill("5");
  await expect(mount).toHaveAttribute("data-current-frame", "5", { timeout: 30_000 });
  await expect(page.getByRole("status")).toContainText("5 / 6");

  // A single-frame file shows the M60 static render — no scrubber anywhere.
  const single = await uploadFixture(request, FIXTURES.workedExample);
  await page.goto(`/files/${single}`);
  await expect(page.locator("[data-mounted=true]")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("slider", { name: "Trajectory frame" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Play|Pause/ })).toHaveCount(0);
});

test("a variable-cell trajectory draws the wireframe per displayed frame — a cell-less frame has no box", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.variableCell);

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  // Frame 0 carries a cell → the wireframe is drawn (frame-0 cell, per the endpoint's object cell).
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "true");

  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });

  // Frame 3 has no cell → the box disappears at the render level (P3: absence renders as absence).
  await slider.fill("3");
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "false", { timeout: 30_000 });
  await expect(mount).toHaveAttribute("data-current-frame", "3");
  // Back to a celled frame → the box returns.
  await slider.fill("1");
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "true", { timeout: 30_000 });
  await expect(mount).toHaveAttribute("data-current-frame", "1");
});

test("a conversion whose output is multi-frame scrubs on the output side", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);
  const submit = await request.post(`${API_URL}/v1/convert`, {
    data: { file_id: fileId, target_format_id: "extxyz", options: {} },
  });
  expect([200, 201, 202]).toContain(submit.status());
  const jobId = String((await submit.json()).job_id);
  const done = await pollJob(request, jobId, ["completed"]);
  const result = done.result as { conversion_id: string; conversion_report?: { status?: string } };
  expect(result.conversion_report?.status).toBe("completed");
  const conversionId = result.conversion_id;

  await page.goto(`/conversions/${conversionId}`);
  await expect(page.getByRole("heading", { name: "Structure", exact: true })).toBeVisible({
    timeout: 30_000,
  });

  // The output keeps all six frames (extXYZ → extXYZ), so the output side scrubs.
  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("status")).toContainText("0 / 6");
  await slider.fill("4");
  await expect(mount).toHaveAttribute("data-current-frame", "4", { timeout: 30_000 });
});

test("an NpT XDATCAR's cell animates — the wireframe persists while the per-frame cell breathes (§5.3)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.nptXdatcar);

  // The data fact first: the endpoint answers a *different* cell per frame (5.6 → 5.8 → 6.0 Å) —
  // the per-frame cell the renderer must follow, never a reused frame-0 lattice (the exact class
  // of loss the M13 golden exists to catch).
  const geo = await request.get(`${API_URL}/v1/files/${fileId}/geometry?frames=0:3`);
  expect(geo.status(), await geo.text()).toBe(200);
  const body = await geo.json();
  expect(body.frame_count).toBe(3);
  const aLengths = body.frames.map(
    (f: { cell: number[][] | null }) => f.cell?.[0]?.[0],
  );
  expect(aLengths).toEqual([5.6, 5.8, 6.0]); // the cell breathes frame to frame

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-has-cell", "true");
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "true");
  await expect(mount).toHaveAttribute("data-current-frame", "0");

  // Scrub across the whole trajectory: the box stays drawn at every frame while the cell it draws
  // changes — the per-frame cell animates (cell breathing), absence never invented anywhere.
  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });
  await slider.fill("2");
  await expect(mount).toHaveAttribute("data-current-frame", "2", { timeout: 30_000 });
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "true");
  await expect(page.getByRole("status")).toContainText("2 / 3");
});

test("a timestep-less XDATCAR scrubs by frame number with no invented time axis (§5.3)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.mdXdatcar);

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });

  // The scrubber is a *frame-number* control: the readout is exactly "frame N / M" — the wire
  // carries no timestep (XDATCAR declares none; the canonical object answers `time: null`, P3), so
  // a frame number is the honest readout, never an invented time label.
  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("status")).toHaveText("0 / 3");
  await slider.fill("2");
  await expect(mount).toHaveAttribute("data-current-frame", "2", { timeout: 30_000 });
  await expect(page.getByRole("status")).toHaveText("2 / 3");

  // No time axis anywhere in the viewer chrome: no unit label (ps/fs/picosecond/femtosecond) and
  // no timestep word — the frame-number readout is the whole time story.
  const structure = page.locator('section[aria-label="Structure"]');
  await expect(structure.getByText(/ps|fs|picosecond|femtosecond|timestep/i)).toHaveCount(0);
});
