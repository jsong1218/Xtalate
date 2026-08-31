import { expect, test, type Page } from "@playwright/test";
import happyRecord from "../components/__fixtures__/conversion.record.json";
import { API_URL, FIXTURES, fixtureBuffer, pollJob, uploadFixture } from "./support/api";

/**
 * Automated WCAG 2.1 A/AA checks in a real browser (MASTER_SPEC Part 7 §4–§5; slice M30-S2). jsdom
 * cannot judge rendered contrast or focus order, so this runs **axe-core** (already a dependency, so
 * no new package) against the real pages and fails on any *serious or critical* barrier — the
 * category that includes color-contrast, missing accessible names, and ARIA misuse. The token-level
 * contrast is additionally pinned dependency-free in `app/globals.contrast.test.ts`; this is the
 * whole-page check that catches a barrier the isolated tokens cannot (a foreground on an unexpected
 * surface, a control with no name).
 *
 * The dense, color-coded page — the conversion record, with its preserved/removed/assumption
 * palette, both report panels, and the provenance strip — is exercised from the real captured record
 * body, so the scan is deterministic and needs no worker run.
 */

async function seriousViolations(page: Page): Promise<{ id: string; help: string }[]> {
  // Playwright transpiles specs to CommonJS, so the global `require` resolves axe-core from
  // node_modules — no new dependency, and the browser gets the same engine axe ships.
  await page.addScriptTag({ path: require.resolve("axe-core") });
  const result = await page.evaluate(async () => {
    // axe is injected onto window by the script tag above.
    const axe = (window as unknown as { axe: { run: (ctx: Document, opts: unknown) => Promise<unknown> } }).axe;
    return (await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    })) as { violations: { id: string; impact: string | null; help: string }[] };
  });
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => ({ id: v.id, help: v.help }));
}

test("the landing page has no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Xtalate" })).toBeVisible();

  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});

test("the conversion record page has no serious accessibility violations", async ({ page }) => {
  // Render a full, loss-carrying record from the real captured body — the page's whole palette on
  // screen at once (summary chips, both report panels, download, provenance).
  // The record GET is served from the captured body (deterministic scan); the route pattern is
  // narrowed to the record itself (`*`, no `/`) so the Structure tab's geometry request goes to
  // the live backend — feeding it the record body would crash the viewer's species legend, and a
  // fabricated "geometry" is exactly what the tab must never render (M60-S2).
  await page.route("**/v1/conversions/*", (route) => route.fulfill({ json: happyRecord }));
  await page.goto(`/conversions/${(happyRecord as { conversion_id: string }).conversion_id}`);
  await expect(page.getByRole("heading", { name: /^Converted/ })).toBeVisible();

  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});

test("the Structure tab's viewer chrome has no serious accessibility violations (M63-S2)", async ({
  page,
  request,
}) => {
  // A live multi-frame file so the chrome under test is the whole bar: the species legend, the
  // frame scrubber (range + play/pause + readout), and the bonds toggle — the canvas itself is
  // not the accessible record (D241), so the scan judges the chrome around it.
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);
  await page.goto(`/f/${fileId}/structure`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("[data-mounted=true]")).toBeVisible({ timeout: 60_000 });

  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});

test("the Compare tab's viewer chrome has no serious accessibility violations (M63-S2)", async ({
  page,
  request,
}) => {
  // Seed a completed conversion whose Compare tab mounts both viewers (multi-frame → POSCAR with
  // a `frame_selection` — the source scrubs, the output holds its frame, and the RMSD overlay +
  // removed-reasons + exported-frame marker render beside the two canvases).
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
  await expect(compare.locator("[data-mounted=true]")).toHaveCount(2, { timeout: 60_000 });

  const violations = await seriousViolations(page);
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});
