import { expect, test } from "@playwright/test";
import { API_URL, FIXTURES, fixtureBuffer, fixturePath, pollJob, uploadFixture } from "./support/api";

/**
 * Keyboard traversal of the wizard (MASTER_SPEC Part 7 §4; slice M30-S2). A conversion must be
 * completable without a mouse: focus must reach the primary controls in a sensible order, and they
 * must activate on Enter. This drives the real browser's focus model — Tab order and Enter
 * activation — which jsdom cannot represent.
 */

test("the primary path is reachable and operable by keyboard from the landing page", async ({
  page,
}) => {
  await page.goto("/");

  // The app shell puts a skip link first (addendum S2), so a keyboard user can jump past the header
  // nav straight to the content. Activating it moves focus to the main region…
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText(/Skip to main content/);
  await page.keyboard.press("Enter");

  // …from which the next Tab lands on the primary call to action, and Enter follows it — no mouse.
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText(/Convert a file/);
  await page.keyboard.press("Enter");
  await page.waitForURL("**/convert");

  // The upload step opens with the consistent back link, then the file chooser — both reachable by
  // keyboard, in that order (the back affordance is the first in-content control on every page, S2).
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText(/Home/);
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText(/Choose a file/);
});

test("the conversion can be chosen and started with the keyboard", async ({ page }) => {
  // Reach an inspected file (setting the file is the OS picker's job; everything after is keyboard).
  await page.goto("/convert");
  await page
    .getByLabel("Choose a file to convert")
    .setInputFiles(fixturePath(FIXTURES.workedExample.file));
  await page.waitForURL("**/files/**");
  await expect(page.getByText(/Detected\s+Extended XYZ/i)).toBeVisible({ timeout: 30_000 });

  // Select the target by focusing it and pressing Enter — the button reflects the choice via
  // aria-pressed, so a screen-reader user hears the selection, not just sees a color change.
  const target = page.getByRole("button", { name: "Plain XYZ", exact: true });
  await target.focus();
  await page.keyboard.press("Enter");
  await expect(target).toHaveAttribute("aria-pressed", "true");

  // Start the conversion from the keyboard. Since v1.1 M39-S4 (B2) the first Enter opens the
  // inline confirm step; the final Convert (Enter again) commits the POST /v1/convert and the
  // wizard advances to the live job page.
  const convert = page.getByRole("button", { name: /^Convert to Plain XYZ$/ });
  await convert.focus();
  await page.keyboard.press("Enter");
  const finalConvert = page.getByRole("button", { name: /^Convert$/ });
  await expect(finalConvert).toBeFocused(); // focus lands on the confirm card's primary action
  await page.keyboard.press("Enter");
  await page.waitForURL("**/convert/**");
});

test("the frame scrubber and the bonds toggle are keyboard-operable (M63-S2)", async ({
  page,
  request,
}) => {
  const fileId = await uploadFixture(request, FIXTURES.multiFrame);
  await page.goto(`/files/${fileId}`);
  await expect(
    page.getByRole("heading", { name: "Structure", exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  const mount = page.locator("[data-mounted=true]");
  await expect(mount).toBeVisible({ timeout: 60_000 });

  // The scrubber is a native range input: the arrow keys move it (the real-browser focus model
  // the M63 keyboard bar asserts — jsdom cannot represent it).
  const slider = page.getByRole("slider", { name: "Trajectory frame" });
  await expect(slider).toBeVisible({ timeout: 30_000 });
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  await expect(mount).toHaveAttribute("data-current-frame", "1", { timeout: 30_000 });
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(mount).toHaveAttribute("data-current-frame", "3", { timeout: 30_000 });
  await page.keyboard.press("ArrowLeft");
  await expect(mount).toHaveAttribute("data-current-frame", "2", { timeout: 30_000 });
  await expect(page.getByRole("status")).toContainText("2 / 6");

  // The bonds toggle is a real button: keyboard-Enter flips it, and the state is announced via
  // aria-pressed (never a color-only signal).
  const toggle = page.getByRole("button", { name: /bonds heuristic/i });
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByText("Bonds are a display heuristic, not file content"),
  ).toBeVisible();
});

test("the Structure/Compare tab control switches tabs by keyboard (M63-S2)", async ({
  page,
  request,
}) => {
  // Seed a completed conversion whose record carries both tabs (multi-frame → POSCAR with a
  // `frame_selection`, exactly the Compare journeys' seeding).
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

  await page.goto(`/conversions/${conversionId}`);
  const structureTab = page.getByRole("tab", { name: "Structure" });
  const compareTab = page.getByRole("tab", { name: "Compare" });
  await expect(compareTab).toBeVisible({ timeout: 30_000 });

  // Keyboard-switch to Compare: focus the tab control (a real button) and activate it with Enter;
  // the panel swaps and aria-selected moves with focus.
  await compareTab.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Compare", exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(compareTab).toHaveAttribute("aria-selected", "true");
  await expect(structureTab).toHaveAttribute("aria-selected", "false");

  // And back to Structure.
  await structureTab.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Structure", exact: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(structureTab).toHaveAttribute("aria-selected", "true");
});
