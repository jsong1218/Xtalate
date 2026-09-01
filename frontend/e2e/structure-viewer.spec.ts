import { expect, test } from "@playwright/test";
import { FIXTURES, uploadFixture } from "./support/api";

/**
 * The M59-S2 render proof (D233/D234), promoted under UI redesign S5 (Rev 1.91) onto its workspace
 * tab: a canonical object renders in embedded Mol\* fed **from the geometry endpoint** with no
 * intermediate format, at the viewer's promoted home `/f/{file_id}/structure` (the same
 * `StructureViewer` the dev spike used to prove). Two load-bearing points, both proven over the
 * running stack:
 *
 *  1. The workspace tab mounts the viewer against `/v1/files/{id}/geometry` — the canvas is live,
 *     the declared atom count reached the loader, and **no request to the only export/download
 *     route (`/v1/download`) ever fires** — the no-hidden-export rule is asserted behaviourally,
 *     not by inspection.
 *  2. Bonds are off by default and the heuristic badge appears iff toggled on (D234) — on the
 *     real mount, not just in jsdom.
 */
test("a canonical object renders in embedded Mol* from the geometry endpoint, with no export", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);

  // The no-hidden-export witness: every request the render makes is recorded, and the only
  // download/export route in the API (`/v1/download/{conversion_id}`) must never be asked for.
  const exportRequests: string[] = [];
  const geometryRequests: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/v1/download")) exportRequests.push(req.url());
    if (req.url().includes(`/v1/files/${fileId}/geometry`)) geometryRequests.push(req.url());
  });

  // The promoted home of the viewer: the workspace's Structure tab (moved out of the dev spike by
  // UI redesign S5). Same viewer, same render proof.
  await page.goto(`/f/${fileId}/structure`);

  // The mount completes: Mol* initializes WebGL, builds the structure from the geometry JSON, and
  // only then marks the container `data-mounted`. The dev server compiles cold, so the timeout is
  // generous — a genuine mount, not a fast-failing stub.
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-atoms", "2");

  // The Mol* render surface is a live canvas inside the viewer container.
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });

  // Fed from the geometry endpoint…
  expect(geometryRequests.length).toBeGreaterThanOrEqual(1);
  // …and never through a hidden export.
  expect(exportRequests).toEqual([]);

  // Bonds-off by default; the heuristic badge appears iff toggled on (D234). S7 (D248) makes the
  // toggle actually *draw* the bonds, so the proof is now render-level: the mount sets
  // `data-bonds-drawn` from whether Mol* added the ball-and-stick representation — false at rest,
  // true only once the heuristic is on — not merely the badge copy.
  await expect(page.getByText(/display heuristic/)).toHaveCount(0);
  await expect(mount).toHaveAttribute("data-bonds-drawn", "false");
  await page.getByRole("button", { name: /Show bonds heuristic/ }).click();
  await expect(
    page.getByText("Bonds are a display heuristic, not file content")
  ).toBeVisible();
  await expect(mount).toHaveAttribute("data-bonds-drawn", "true");
  await page.getByRole("button", { name: /Hide bonds heuristic/ }).click();
  await expect(page.getByText(/display heuristic/)).toHaveCount(0);
  await expect(mount).toHaveAttribute("data-bonds-drawn", "false");
});

/**
 * S7 (D248) viewer controls on the promoted Structure tab: the reset-view control, the expand
 * overlay (a real focus-trapped dialog that Escape closes), and the theme-aware Mol\* background.
 * The WebGL background colour itself is not readable from Playwright, so dark mode is proven at the
 * two observable seams — `<html data-theme="dark">` after the header toggle, and the canvas staying
 * mounted (`data-mounted="true"`) across the theme flip rather than tearing down and re-mounting.
 */
test("the Structure tab's reset/expand controls work and the viewer survives a theme flip", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  await page.goto(`/f/${fileId}/structure`);

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });

  // Reset view is present and clickable; the mount survives the camera reset (no re-mount).
  await page.getByRole("button", { name: /reset view/i }).click();
  await expect(mount).toBeVisible();

  // Expand opens the focus-trapped dialog; Escape closes it and no dialog remains.
  await page.getByRole("button", { name: /expand/i }).click();
  const dialog = page.getByRole("dialog", { name: /structure viewer/i });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Dark mode: the header toggle flips `<html data-theme>`; the viewer re-themes its background in
  // place — the canvas stays mounted across the flip (theme-aware, not a re-mount).
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /switch to dark mode/i }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("[data-mounted=true]")).toBeVisible();
});
