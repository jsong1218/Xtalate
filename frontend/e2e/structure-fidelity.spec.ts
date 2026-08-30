import { expect, test } from "@playwright/test";
import { API_URL, FIXTURES, seedCompletedConversion, uploadFixture } from "./support/api";

/**
 * The Structure tab's static-render fidelity (v1.6 M60-S2, Part 7 §4/§6): the legend lists the
 * file's elements, the unit-cell wireframe appears **only when a cell is present**, and a
 * cell-less file renders atoms in open space with the explicit no-simulation-cell caption and
 * no box — the P3 absence invariant, proven in the browser over the live stack. The M63-S1
 * release pass adds the **bonds honesty journey** (D234, impl-plan §5.6): bonds are a display
 * heuristic, off by default, with a persistent badge when enabled, and in no report anywhere.
 *
 * Formats exercised here: **XYZ** (cell-less), **POSCAR** and **CIF** (celled) — plus **extXYZ**
 * in `structure-tab.spec.ts` (celled). The remaining seven+ formats (XDATCAR, ASE `.traj`, …)
 * are covered by the loader unit tests plus the geometry endpoint's format-agnostic canonical
 * JSON (the wire form is identical regardless of source format, D232). The fixtures are copied
 * from the golden corpus (`tests/golden/xyz/water-traj/`, `poscar/nacl-primitive/`,
 * `cif/zno-hexagonal-p1/`).
 */
test("a cell-less XYZ renders atoms in open space: no box, and the caption says why (P3)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.noCellXyz);

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  // The mount is live with the atoms…
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-atoms", "3"); // O + 2 H
  // …and cell-less: no wireframe, ever. `data-has-cell` mirrors the endpoint's input answer;
  // `data-unitcell-drawn` is the render-level proof — Mol* actually drew no box (P3), so the
  // absence invariant is asserted where it lives, not on the input.
  await expect(mount).toHaveAttribute("data-has-cell", "false");
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "false");
  // The explicit caption — absence rendered as absence, never a fabricated box.
  await expect(page.getByText(/declares no simulation cell/)).toBeVisible();
  // The legend lists exactly the file's elements (the icon+text a11y rule).
  await expect(page.getByTestId("legend-row-O")).toHaveText("O");
  await expect(page.getByTestId("legend-row-H")).toHaveText("H");
});

test("a celled POSCAR renders the unit-cell wireframe and its element legend", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.celledPoscar);

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  // The source carries a 5.64 Å NaCl cell → the wireframe is drawn, and no caption.
  await expect(mount).toHaveAttribute("data-has-cell", "true");
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "true");
  await expect(page.getByText(/declares no simulation cell/)).toHaveCount(0);
  await expect(page.getByTestId("legend-row-Na")).toHaveText("Na");
  await expect(page.getByTestId("legend-row-Cl")).toHaveText("Cl");
});

test("a celled CIF renders the unit-cell wireframe and its element legend", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.celledCif);

  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });

  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });
  await expect(mount).toHaveAttribute("data-has-cell", "true");
  await expect(mount).toHaveAttribute("data-unitcell-drawn", "true");
  await expect(page.getByTestId("legend-row-Zn")).toHaveText("Zn");
  await expect(page.getByTestId("legend-row-O")).toHaveText("O");
});

test("bonds are a display heuristic: off by default, the persistent badge when enabled, in no report (D234)", async ({
  page,
  request,
}) => {
  const { conversionId } = await seedCompletedConversion(request);

  // The D234 guarantee at the data level first: neither report body mentions bonds at all — the
  // Canonical Model holds no bonds, so no report ever will (no-report-mentions-bonds, §5.6).
  const recordResp = await request.get(`${API_URL}/v1/conversions/${conversionId}`);
  expect(recordResp.ok(), await recordResp.text()).toBeTruthy();
  const record = (await recordResp.json()) as {
    conversion_report: unknown;
    validation_report: unknown;
  };
  expect(JSON.stringify(record.conversion_report)).not.toMatch(/bond/i);
  expect(JSON.stringify(record.validation_report)).not.toMatch(/bond/i);

  await page.goto(`/conversions/${conversionId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });

  // Off by default: the toggle is the *only* place "bond" appears on the whole rendered page — no
  // badge, and no report panel mentions bonds. The viewer's atoms-only representation (D234).
  const bodyText = () => page.locator("body").innerText();
  expect((await bodyText()).match(/bond/gi)).toHaveLength(1);

  // The accessible name flips with the state ("Show…" → "Hide…"), so match the whole heuristic
  // control, not one label.
  const toggle = page.getByRole("button", { name: /bonds heuristic/i });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await toggle.click();

  // Enabled → the persistent heuristic badge appears and states the honesty plainly; the toggle
  // and the badge are then the only two "bond" mentions on the page.
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByText("Bonds are a display heuristic, not file content"),
  ).toBeVisible();
  expect((await bodyText()).match(/bond/gi)).toHaveLength(2);

  // Persistent, not a transient toast: the badge stays part of the viewer chrome while the toggle
  // is on — still visible after the mount settles, and it names the heuristic in full.
  await expect(
    page.getByText("Bonds are a display heuristic, not file content"),
  ).toBeVisible();
});
