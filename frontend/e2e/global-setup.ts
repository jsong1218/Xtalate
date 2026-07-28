import { request } from "@playwright/test";

/**
 * Warm the dev server's route compiler before the suite runs (M30-S2 reliability).
 *
 * The compose `frontend` service is `next dev`, which compiles each route **lazily on first
 * request**. In CI the stack is always freshly built, so the first e2e run hits every route cold —
 * and with the suite fully parallel, several workers can pile onto the single-threaded compiler at
 * once and stall a navigation past its timeout. Requesting each route once, serially, here pays that
 * compile cost up front (Next blocks the response until the route is built), so the tests themselves
 * run against warm routes. Dynamic-segment routes are warmed with a throwaway id — the route
 * *module* compiles regardless of whether that id resolves.
 *
 * Best-effort: a non-200 (e.g. a warmup id that 404s) still triggers compilation, so failures here
 * are swallowed. This only makes the suite faster and steadier; it asserts nothing.
 */
export default async function globalSetup(): Promise<void> {
  const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
  const routes = [
    "/",
    "/convert",
    "/formats",
    "/files/warmup",
    "/convert/warmup",
    "/conversions/warmup",
  ];
  const ctx = await request.newContext({ baseURL });
  for (const route of routes) {
    try {
      await ctx.get(route, { timeout: 60_000 });
    } catch {
      // Compilation is the point; a slow or non-200 warmup response is not a failure.
    }
  }
  await ctx.dispose();
}
