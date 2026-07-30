import { expect, test } from "@playwright/test";

/**
 * The format explorer, end to end against the compose stack (MASTER_SPEC Part 7 §2.7; slice M33-S1).
 *
 * The grid is generated from `GET /v1/capabilities`, so a component test proves it renders *a* map;
 * only the running stack proves it renders *this instance's real registry* — the actual endpoint
 * shape the server component fetches and casts. This is the milestone's "Done means" made literal:
 * "can extXYZ hold X?" is answerable in two clicks without leaving the browser — open /formats, click
 * the format, read its declaration.
 */
test("answers a capability question in two clicks, generated from the live registry", async ({
  page,
}) => {
  await page.goto("/formats");
  await expect(page.getByRole("heading", { level: 1, name: "Formats" })).toBeVisible();

  // A real built-in format is a row, with a real canonical field as a column — nothing hard-coded,
  // both come straight from the registry the backend serves.
  const extxyz = page.getByRole("link", { name: "Extended XYZ" });
  await expect(extxyz).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Total energy" })).toBeVisible();

  // Second click: the detail page, with required_fields framed as the recovery it foreshadows.
  await extxyz.click();
  await expect(page.getByRole("heading", { level: 1, name: "Extended XYZ" })).toBeVisible();
  await expect(page.getByText(/Converting into Extended XYZ requires/i)).toBeVisible();
});
