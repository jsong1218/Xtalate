import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the end-to-end journeys (D92; filled out in M30). In M26 it carries a
 * single smoke test that the app shell serves. The suite runs against a already-running stack —
 * `docker compose up` (or `next dev`) — pointed at by `E2E_BASE_URL`; CI starts the compose stack
 * before invoking it (M30).
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
