import { expect, test, type Locator } from "@playwright/test";
import { API_URL, FIXTURES, pollJob, uploadFixture } from "./support/api";

/**
 * Deterministic layout-regression guard (v2.0 addendums; item 10).
 *
 * Phase B fixed a class of visual bug — conversion-report text that jumbled and overlapped — that a
 * unit test cannot see (jsdom has no layout) and that a WebGL pixel snapshot would only catch
 * flakily (GPU/OS-dependent, the very flake class item 8 removes). Instead this asserts a *layout
 * invariant* in a real browser: rendered report rows must stack, never overlap in two dimensions at
 * once, and never overflow their column horizontally. Two rows in different columns are horizontally
 * disjoint; two rows in one column are vertically disjoint; a jumble is a true 2D intersection —
 * which is exactly what we forbid. Run under both the dark and light palettes, since a theme swap
 * changes font metrics and padding tokens and could reintroduce the overlap in only one theme.
 *
 * (Compare-panel alignment — the other Phase B layout fix — is already guarded by the canvas
 * top-offset assertion in compare-tab.spec.ts; this spec owns the text-overlap class.)
 */

/** Two layout boxes intersect in both axes by more than EPS px (a real jumble, not a touching border). */
const EPS = 1;
interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}
function overlaps2D(a: Box, b: Box): boolean {
  const xOverlap = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const yOverlap =
    Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return xOverlap > EPS && yOverlap > EPS;
}

async function boxesOf(rows: Locator): Promise<Box[]> {
  const count = await rows.count();
  const boxes: Box[] = [];
  for (let i = 0; i < count; i += 1) {
    const box = await rows.nth(i).boundingBox();
    if (box) boxes.push(box);
  }
  return boxes;
}

test("the conversion report's rows never overlap and never overflow, in dark and light themes", async ({
  page,
  request,
}) => {
  // A forced-loss conversion (worked example → POSCAR) so the report carries many rows across
  // outcomes — lost, kept, assumed — the dense case where a jumble would first appear.
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  const resp = await request.post(`${API_URL}/v1/convert`, {
    data: {
      file_id: fileId,
      target_format_id: "poscar",
      options: { allow_recovery: true },
    },
  });
  expect([200, 201, 202]).toContain(resp.status());
  const jobId = String((await resp.json()).job_id);
  const done = await pollJob(request, jobId, ["completed"]);
  expect(done.state).toBe("completed");
  const conversionId = String(
    (done.result as { conversion_id: string }).conversion_id,
  );

  await page.goto(`/f/${fileId}/report/${conversionId}`);
  const panel = page.getByTestId("report-columns").first();
  await expect(panel).toBeVisible({ timeout: 30_000 });
  const rows = panel.locator("[data-report-row]");
  await expect(rows.first()).toBeVisible({ timeout: 30_000 });
  const rowCount = await rows.count();
  expect(
    rowCount,
    "the forced-loss report must render rows to check",
  ).toBeGreaterThan(3);

  const panelBox = await panel.boundingBox();
  expect(panelBox).not.toBeNull();

  for (const theme of ["dark", "light"] as const) {
    await page.evaluate(
      (t) => document.documentElement.setAttribute("data-theme", t),
      theme,
    );
    // Let the palette swap settle (token-driven padding/line-height can shift box metrics).
    await expect(rows.first()).toBeVisible();

    // Only rows actually in layout have a box (a collapsed group's rows are display:none and are
    // skipped) — the report's outcome groups are expanded by default, so most rows render.
    const boxes = await boxesOf(rows);
    expect(
      boxes.length,
      `[${theme}] visible rows must have layout boxes`,
    ).toBeGreaterThan(3);

    // Every row is a real, non-degenerate box.
    for (const b of boxes) {
      expect(
        b.width,
        `[${theme}] a row collapsed to zero width`,
      ).toBeGreaterThan(0);
      expect(
        b.height,
        `[${theme}] a row collapsed to zero height`,
      ).toBeGreaterThan(0);
    }

    // No two rows form a true 2D overlap — the jumble Phase B fixed.
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        expect(
          overlaps2D(boxes[i], boxes[j]),
          `[${theme}] report rows ${i} and ${j} overlap in 2D (text jumble)`,
        ).toBe(false);
      }
    }

    // No row overflows the columns container horizontally (a small tolerance for sub-pixel rounding).
    for (let i = 0; i < boxes.length; i += 1) {
      expect(
        boxes[i].x + boxes[i].width,
        `[${theme}] row ${i} overflows the report panel's right edge`,
      ).toBeLessThanOrEqual(panelBox!.x + panelBox!.width + 2);
    }
  }
});
