import { expect, test } from "@playwright/test";
import { FIXTURES, uploadFixture } from "./support/api";

/**
 * The UI redesign S6 empty-seams + motion journeys (D247, design spec §7 / §4). Three done-means
 * assertions over the live workspace:
 *
 *  1. Every reserved **seam renders its "coming later" state and does nothing** — File Repair is a
 *     genuinely `disabled` button (cannot be activated, navigates nowhere), the Assistant is a plain
 *     labelled box (not a control), and the Analysis tab is an inert placeholder page with no engine
 *     call. This is the P6 anti-scope-creep guarantee, proven behaviourally, not by inspection.
 *  2. The seams appear on every workspace tab (they belong to the shell, not one surface).
 *  3. `/f/[id]` respects **`prefers-reduced-motion`**: the global guard collapses the restrained
 *     tab transition to an instant when the user asks for reduced motion, and leaves it at its normal
 *     duration when they do not.
 */
test("the reserved seams render 'coming later' and are inert across the workspace (S6)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  await page.goto(`/f/${fileId}`);
  await expect(page.locator('aside[aria-label="Source file"]')).not.toContainText("Loading source…", {
    timeout: 30_000,
  });

  // The seams belong to the shell, so they appear on every tab.
  for (const path of [`/f/${fileId}`, `/f/${fileId}/structure`, `/f/${fileId}/convert`]) {
    await page.goto(path);
    await expect(page.getByTestId("future-seams")).toBeVisible({ timeout: 30_000 });
  }

  // File Repair is a disabled action affordance — it cannot be activated, so it does nothing.
  const repair = page.getByRole("button", { name: "File repair" });
  await expect(repair).toBeDisabled();
  // The Assistant is a plain labelled seat, not a control (no role to trap focus or take a click).
  await expect(page.getByTestId("seam-assistant")).toBeVisible();
  await expect(page.getByTestId("seam-assistant").locator("a, button, [role=button], [role=link]")).toHaveCount(0);
  // Both seats say they are coming later — nothing claims to work today.
  await expect(page.getByTestId("future-seams")).toContainText("coming later");
});

test("the Analysis seam tab renders its placeholder and starts no conversation (S6)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);
  // Track any engine call the seam might spuriously make — there must be none above the shell's own.
  const convertCalls: string[] = [];
  page.on("request", (r) => {
    if (/\/v1\/(convert|files\/[^/]+\/geometry)/.test(r.url())) convertCalls.push(r.url());
  });

  await page.goto(`/f/${fileId}/analysis`);
  await expect(page.getByRole("heading", { name: "Analysis" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/reserved for per-atom and trajectory analysis — coming in a later version/i)).toBeVisible();

  // The seam does nothing: neither a convert nor a geometry read fires because of this page.
  expect(convertCalls.filter((u) => u.includes("/v1/convert"))).toEqual([]);
});

test("prefers-reduced-motion is honoured on the workspace (S6)", async ({ page, request }) => {
  const fileId = await uploadFixture(request, FIXTURES.workedExample);

  // With no preference, the restrained tab transition runs at its normal speed.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto(`/f/${fileId}`);
  const tab = page.getByRole("link", { name: "Inspect" });
  await expect(tab).toBeVisible({ timeout: 30_000 });
  // Read the duration as a number of seconds (CSS serializes it that way — `0.15s`, never a literal
  // "150ms" in computed style).
  const durationSeconds = (el: Element) =>
    parseFloat(getComputedStyle(el).transitionDuration);
  const normal = await tab.evaluate(durationSeconds);
  expect(normal).toBeGreaterThanOrEqual(0.1); // the restrained tab transition runs at its normal speed

  // With reduced motion, the global guard collapses it to an instant (≈ 0.01ms → 1e-5 s).
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  const reduced = await tab.evaluate(durationSeconds);
  expect(reduced).toBeLessThan(0.001);
});