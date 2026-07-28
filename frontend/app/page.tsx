import Link from "next/link";
import { apiClient } from "@/lib/api/client";
import { LossTag } from "@/components/loss/icons";

// The live figures (format count, size cap) must describe the *running* instance, never the build
// machine: Part 9 §2 fixes only the API origin at build time — limits and capabilities are learned
// at runtime. Without this, `next build` prerenders `/` statically and bakes build-time values
// (nulls, in CI) into the page forever.
export const dynamic = "force-dynamic";

/**
 * Landing (`/`) — the front door (MASTER_SPEC Part 7 §2.1). It orients a first-time visitor around
 * the one idea the product turns on — **every conversion produces a report of what it kept, lost, or
 * assumed** — before it asks for a file, and it teaches the §4 loss vocabulary (✓ / ✗ / ◆ / ⚠) once
 * up front so it is "learned once, trusted everywhere" on the pages that follow.
 *
 * Server Component: the static orientation paints fast (Part 7 §5.3). The live figures (format
 * count, instance size cap) are additive — if the API is unreachable (`next dev` with no backend)
 * the page still renders; the numbers are simply omitted, never faked.
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
    <main className="space-y-10">
      <section className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight">Xtalate</h1>
        <p className="max-w-2xl text-lg text-slate-700">
          The trusted translation layer between computational chemistry file formats — a converter
          that tells you exactly what it kept, what it lost, and why.
        </p>
        <p className="max-w-2xl text-slate-600">
          Every conversion produces a <strong>Conversion Report</strong>: a line-by-line record of
          each field that was preserved, dropped because the target format can&rsquo;t hold it, or
          filled in by an explicit recovery choice. Nothing is changed silently.
        </p>
        <div className="flex flex-wrap items-center gap-4 pt-1">
          <Link
            href="/convert"
            className="inline-block rounded-md bg-slate-900 px-5 py-2.5 font-medium text-white"
          >
            Convert a file
          </Link>
          <Link href="/formats" className="text-slate-600 underline">
            Explore formats
          </Link>
        </div>
        {formatCount !== null ? (
          <p className="text-sm text-slate-500">
            {formatCount} formats supported
            {maxMb !== null ? ` · files up to ${maxMb} MB on this instance` : ""}.
          </p>
        ) : null}
      </section>

      {/* The three-step strip — introduces the §4 loss iconography before any report is shown. */}
      <section aria-label="How a conversion works" className="grid gap-4 sm:grid-cols-3">
        <Step
          n={1}
          title="Upload & inspect"
          body="See what your file actually contains — every canonical field marked present or absent."
        >
          <LossTag kind="preserved">Present</LossTag>
        </Step>
        <Step
          n={2}
          title="Preview the loss"
          body="Before converting, see what the target format cannot express and what it will drop."
        >
          <LossTag kind="removed">Dropped</LossTag>
        </Step>
        <Step
          n={3}
          title="Convert with a report"
          body="Anything recovered is recorded as an assumption; warnings are named, never buried."
        >
          <span className="inline-flex flex-wrap gap-3">
            <LossTag kind="assumption">Assumed</LossTag>
            <LossTag kind="warning">Warned</LossTag>
          </span>
        </Step>
      </section>
    </main>
  );
}

function Step({
  n,
  title,
  body,
  children,
}: {
  n: number;
  title: string;
  body: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 p-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">
          {n}
        </span>
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      </div>
      <p className="text-sm text-slate-600">{body}</p>
      <div>{children}</div>
    </div>
  );
}
