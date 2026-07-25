import Link from "next/link";
import { apiClient } from "@/lib/api/client";

/**
 * Landing (`/`) — the app shell wired to the real API (the M26 "done means"). The full three-block
 * orientation of Part 7 §2.1 (the Conversion Report concept, the ✓/✗/⚠ three-step strip that
 * teaches the §4 iconography) is M28; here the shell renders and reads `GET /v1/capabilities` and
 * `GET /v1/limits` through the typed client to prove the stack is live end to end.
 *
 * Server Component: shared links first-paint fast (Part 7 §5.3). If the API is unreachable (e.g.
 * `next dev` with no backend), the shell still renders — the live figures are additive, never a
 * hard dependency of the page loading.
 */
async function loadOverview(): Promise<{ formatCount: number | null; maxMb: number | null }> {
  try {
    const [caps, limits] = await Promise.all([
      apiClient.GET("/v1/capabilities"),
      apiClient.GET("/v1/limits"),
    ]);
    const formatCount = caps.data ? Object.keys(caps.data).length : null;
    const maxMb = limits.data ? Math.floor(limits.data.max_upload_bytes / (1024 * 1024)) : null;
    return { formatCount, maxMb };
  } catch {
    return { formatCount: null, maxMb: null };
  }
}

export default async function LandingPage() {
  const { formatCount, maxMb } = await loadOverview();

  return (
    <main className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Xtalate</h1>
      <p className="max-w-2xl text-lg text-slate-700">
        The trusted translation layer between computational chemistry file formats — a converter
        that tells you exactly what it kept, what it lost, and why.
      </p>
      <div className="flex items-center gap-4">
        <Link
          href="/convert"
          className="inline-block rounded-md bg-slate-900 px-4 py-2 font-medium text-white"
        >
          Convert a file
        </Link>
        <Link href="/formats" className="text-slate-600 underline">
          What can each format hold?
        </Link>
      </div>
      {formatCount !== null && (
        <p className="text-sm text-slate-500">
          {formatCount} formats supported
          {maxMb !== null ? ` · files up to ${maxMb} MB on this instance` : ""}.
        </p>
      )}
    </main>
  );
}
