import { expect, test } from "@playwright/test";
import { FIXTURES, uploadFixture } from "./support/api";

/**
 * The Structure tab's static-render fidelity (v1.6 M60-S2, Part 7 §4/§6): the legend lists the
 * file's elements, the unit-cell wireframe appears **only when a cell is present**, and a
 * cell-less file renders atoms in open space with the explicit no-simulation-cell caption and
 * no box — the P3 absence invariant, proven in the browser over the live stack.
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
  // …and cell-less: no wireframe, ever.
  await expect(mount).toHaveAttribute("data-has-cell", "false");
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
  await expect(page.getByTestId("legend-row-Zn")).toHaveText("Zn");
  await expect(page.getByTestId("legend-row-O")).toHaveText("O");
});
