import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Vitest config for component + unit tests (D91). jsdom environment for Testing Library; the
 * Playwright e2e suite (D92) lives under `e2e/` and is excluded here so the two layers never
 * run in the same process.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: [
      "{app,components,lib}/**/*.{test,spec}.{ts,tsx}",
      // The tailwind token test lives beside the config it pins (UI redesign S1) — outside the
      // component dirs above, so it is matched explicitly or it would silently never run in CI.
      "tailwind.config.test.ts",
    ],
    exclude: ["e2e/**", "node_modules/**"],
  },
});
