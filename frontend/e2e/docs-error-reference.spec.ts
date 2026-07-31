import { expect, test } from "@playwright/test";
import { API_URL } from "./support/api";

/**
 * The docs site and its per-code error reference, end to end against the compose stack (MASTER_SPEC
 * Part 6 §6, Part 7 §1; slice M34-S1).
 *
 * The milestone promise is that every `documentation_url` an error envelope emits *resolves*. A
 * component lint already proves all 25 codes have a section in `docs/errors.md`; this proves the
 * rendering chain the lint cannot: a real API error carries a `#{code}` anchor, and that anchor lands
 * on a rendered `/docs/errors` section on the running site. `FORMAT_NOT_FOUND` is the vehicle because
 * it is public, unauthenticated, and deterministic — no upload required.
 */
test("an API error's documentation anchor resolves on the rendered error reference", async ({
  page,
}) => {
  // A real error envelope from the running backend (an unknown format is a clean, public 404).
  const resp = await page.request.get(`${API_URL}/v1/capabilities/definitely-not-a-format`);
  expect(resp.status()).toBe(404);
  const envelope = (await resp.json()) as { error: { code: string; documentation_url: string } };
  expect(envelope.error.code).toBe("FORMAT_NOT_FOUND");

  // The envelope points at the code's anchor, lower-cased — the contract the docs site must satisfy.
  const anchor = envelope.error.code.toLowerCase();
  expect(envelope.error.documentation_url).toMatch(new RegExp(`#${anchor}$`));

  // That anchor resolves on the running docs site: the reference renders and scrolls to the section.
  await page.goto(`/docs/errors#${anchor}`);
  await expect(page.getByRole("heading", { level: 1, name: "Error reference" })).toBeVisible();
  const section = page.locator(`#${anchor}`);
  await expect(section).toBeVisible();
  await expect(section).toHaveText("FORMAT_NOT_FOUND");
});

test("the docs index links into the rendered corpus", async ({ page }) => {
  await page.goto("/docs");
  await expect(page.getByRole("heading", { level: 1, name: "Documentation" })).toBeVisible();

  // The nav is generated from the one page registry; the error reference is one committed Markdown
  // file rendered as a page, not a second copy of the content.
  await page.getByRole("navigation", { name: "Documentation" }).getByText("Quickstart").click();
  await expect(page).toHaveURL(/\/docs\/quickstart$/);
  await expect(page.getByRole("heading", { level: 1, name: "Quickstart" })).toBeVisible();
});
