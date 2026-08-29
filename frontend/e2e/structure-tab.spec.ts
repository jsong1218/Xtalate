import { expect, test } from "@playwright/test";
import {
  FIXTURES,
  seedCompletedConversion,
  seedRefusedConversion,
  uploadFixture,
} from "./support/api";

/**
 * The Structure tab journeys (v1.6 M60-S1, Part 7 §6): the tab seam on both record pages renders
 * the structure **from the geometry endpoint** with honest states. Two load-bearing points proven
 * over the running stack:
 *
 *  1. The tab mounts the M59 `StructureViewer` on `/files/[file_id]` (the file's own geometry) and
 *     on `/conversions/[conversion_id]` (the conversion's **output** geometry) — the canvas is
 *     live, the declared atom count reached the loader.
 *  2. The honest states: a **refused** conversion renders no viewer (the RefusalPanel is the
 *     page), and an expired-output geometry shows the expired copy while the reports still render
 *     — reports-outlive-bytes, in the browser (D232).
 */
test("the file page's Structure tab renders the file's geometry from the endpoint", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  // The mount completes: Mol* initializes WebGL, builds the structure from the geometry JSON, and
  // only then marks the container `data-mounted` (the worked example is a 2-atom molecule).
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-atoms", "2");
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
});

test("the conversion page's Structure tab renders the output geometry", async ({
  page,
  request,
}) => {
  const { conversionId } = await seedCompletedConversion(request);

  await page.goto(`/conversions/${conversionId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  // The conversion's output (extXYZ → plain XYZ) has no cell — the atoms render in open space, no
  // box (the absence caption is S2; this journey proves the seam renders from side=output).
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
});

test("a refused conversion shows no Structure tab — the refusal is the page", async ({
  page,
  request,
}) => {
  const { conversionId } = await seedRefusedConversion(request);

  await page.goto(`/conversions/${conversionId}`);
  await expect(
    page.getByRole("heading", { name: /Refused — no file was written/ }),
  ).toBeVisible({ timeout: 30_000 });
  // No viewer, no tab: a refused conversion has no output bytes (Part 6 §1).
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toHaveCount(0);
});

test("an expired-output conversion shows the expired state while the reports still render", async ({
  page,
  request,
}) => {
  const { conversionId } = await seedCompletedConversion(request);

  // The one honest state that cannot be produced live without waiting out the byte lifecycle:
  // the record loads from persisted rows while its geometry answers `410 OUTPUT_EXPIRED` (D232).
  // Intercept only the geometry route — the record itself is real, so the reports below are real.
  await page.route("**/v1/conversions/**/geometry**", (route) =>
    route.fulfill({
      status: 410,
      json: {
        error: {
          code: "OUTPUT_EXPIRED",
          message: "The output bytes have expired.",
          details: {},
          request_id: "e2e-expired-geometry",
          documentation_url: "http://localhost:8000/docs/errors",
        },
      },
    }),
  );

  await page.goto(`/conversions/${conversionId}`);

  // Expired, not "not found": the tab says the bytes are gone…
  await expect(page.getByText(/The output bytes have expired/)).toBeVisible({ timeout: 30_000 });
  // …and reports-outlive-bytes holds in the browser: the reports below still render, no viewer.
  await expect(page.getByRole("heading", { name: "Conversion report" })).toBeVisible();
  await expect(page.locator("[data-mounted=true]")).toHaveCount(0);
});
