import { apiClient } from "@/lib/api/client";
import { RecentsStrip } from "@/components/history/RecentsStrip";
import { LossTag } from "@/components/loss/icons";
import { buttonClasses } from "@/components/ui/Button";
import { LandingUpload } from "@/components/upload/LandingUpload";

// The live figures (format count, size cap) must describe the *running* instance, never the build
// machine: Part 9 §2 fixes only the API origin at build time — limits and capabilities are learned
// at runtime. Without this, `next build` prerenders `/` statically and bakes build-time values
// (nulls, in CI) into the page forever.
export const dynamic = "force-dynamic";

/**
 * Landing (`/`) — the workbench's empty-state demo front door (v2.0 addendums Task 12; design spec
 * §"Empty state (demo front door)"). It replaces the old scroll-style marketing page (a long hero +
 * a three-step vocabulary strip) now that the page renders inside the workbench center
 * (`WorkbenchLayout`) alongside a persistent toolbar, sources rail, and inspector: a first-time
 * visitor no longer needs a full page of orientation before the one thing this front door exists to
 * do — take a file. The hero stays a one-liner; the §4 loss vocabulary (✓ / ✗ / ◆ / ⚠) folds into a
 * compact legend beside the dropzone instead of its own three-card section.
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
    <main className="space-y-8">
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">Xtalate</h1>
        <p className="max-w-2xl text-body">
          Loss-aware file conversion for computational chemistry — every conversion reports exactly
          what it kept, what it dropped, and why. Nothing is changed silently.
        </p>
        {/*
          The one primary call to action — an anchor to the upload section below (UI redesign S2:
          with `/convert` redirected to `/`, upload lives on the landing, so the CTA opens the
          dropzone instead of a route). The secondary destinations (Formats · History · Docs) live
          in the workbench toolbar, on every page.
        */}
        <div className="flex flex-wrap items-center gap-4 pt-1">
          <a href="#upload" className={buttonClasses("primary", "lg")}>
            Convert a file
          </a>
        </div>
      </section>

      {/* Upload — the front door's action (UI redesign S2): the dropzone the hero CTA opens. */}
      <section id="upload" aria-label="Convert a file" className="scroll-mt-4 space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">Convert a file</h2>

        {/* The compact §4 vocabulary legend (replaces the old three-step marketing strip): the same
            four states a report will use, learned once, right beside the dropzone that produces the
            first one. */}
        <div
          aria-label="Loss vocabulary"
          className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-md border border-line px-3 py-2"
        >
          <LossTag kind="preserved">Preserved</LossTag>
          <LossTag kind="removed">Dropped</LossTag>
          <LossTag kind="assumption">Assumed</LossTag>
          <LossTag kind="warning">Warned</LossTag>
        </div>

        <LandingUpload />

        {formatCount !== null ? (
          <p className="text-sm text-faint">
            {formatCount} formats supported
            {maxMb !== null ? ` · files up to ${maxMb} MB on this instance` : ""}.
          </p>
        ) : null}
      </section>

      {/* One click back to a file you were just working on (UI redesign S4, D246): the recent-files
          strip merges this browser's recents with /v1/history; hidden entirely until there is one.
          The workbench Sources rail (WorkbenchLayout → SourceRail) renders the same merged list on
          every route, but it is `hidden … md:flex` (SourceRail.tsx) — invisible below the `md`
          breakpoint — so this strip stays here too: it is the only "pick up where I left off"
          surface a narrow-viewport visitor sees. */}
      <div className="max-w-2xl">
        <RecentsStrip />
      </div>
    </main>
  );
}
