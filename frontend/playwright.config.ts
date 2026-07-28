import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the end-to-end journeys (D92; M30-S1). The suite runs against an
 * already-running stack — `docker compose up`, or a locally-run `next dev` + backend — and asserts
 * the honest states of the whole product in a real browser:
 *
 *  - the browser drives the frontend at `E2E_BASE_URL` (default `http://localhost:3000`);
 *  - a few specs seed server state (an `awaiting_recovery` pause) by talking to the backend directly
 *    at `E2E_API_URL` (default `http://localhost:8000`) — setup is not the thing under test, and a
 *    direct call keeps multipart uploads off the Next dev proxy (`e2e/support/api.ts`).
 *
 * CI brings the compose stack up before invoking this (the `e2e` job in `main.yml`), with a small
 * `XTALATE_MAX_UPLOAD_BYTES` so the oversized-upload journey stays kilobyte-scale.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  // One worker, deliberately. The suite shares a single backend that enforces the real product
  // limit of `max_concurrent_jobs = 4` (Part 6 §5), and one journey seeds an `awaiting_recovery`
  // pause that stays non-terminal for the rest of the run — permanently holding one of those four
  // slots. Running fully parallel let several browsers' in-flight jobs plus that lingering seed
  // exceed four at once, so an unrelated inspect was refused `429 TOO_MANY_ACTIVE_JOBS` — the
  // harness fighting a real limit no journey asserts. Serial keeps instantaneous active jobs at the
  // seed (1) plus the current test's own (≤2), always under the cap, and it also removes any
  // thundering herd on the lazy `next dev` route compiler (which `globalSetup` warms up front
  // regardless). Reliability over a few seconds of wall-clock on a suite this small.
  fullyParallel: false,
  globalSetup: "./e2e/global-setup.ts",
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // In CI: GitHub annotations on the PR/commit, plus a self-contained HTML report the `e2e` job
  // uploads as an artifact on failure (the first thing a maintainer opens for a CI-only failure).
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : "list",
  // The compose `frontend` service runs `next dev`, which compiles a route on its first request, and
  // the worker-backed convert path is a poll-to-completion — so per-test and per-assertion budgets
  // are generous. They bound a genuinely stuck stack; they are not the expected duration.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
