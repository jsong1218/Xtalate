"use client";

import { usePathname } from "next/navigation";
import { useInspection } from "@/lib/api/useInspection";

/**
 * The workbench status bar (bottom row of `WorkbenchLayout`, design spec §"Shell architecture" —
 * Status bar row: "file · format · atoms · frames · job state · demo/auto-expire indicator").
 *
 * Task 7 stubbed this as a bare landmark; this task fills it in, following the same self-contained
 * pattern `Toolbar` (Task 8) and `Inspector` (Task 10) already established: no props from
 * `WorkbenchLayout`, the active file id is derived from `usePathname()`, and the file facts come
 * from the *same* `useInspection(fileId)` hook the Inspector and the Inspect tab already call — one
 * request per file id, deduped by react-query, never a bespoke fetch here.
 *
 * **Job state is deliberately omitted.** The design row lists it, but there is no route-independent
 * way to reach it without inventing new wiring: a job id only exists as the `?job=` search param on
 * the Convert tab's own URL (`components/workspace/ConversionJob.tsx`'s `jobHref`), there is no
 * global "active job" store, and the Report/Structure/Analysis/overview routes carry no job id at
 * all. Reading `useSearchParams()` here and polling a second job query — for a fact that would be
 * blank on 4 of the 5 per-file routes — would be exactly the kind of fetch this component is asked
 * not to invent. So the status bar shows file · format · atoms · frames and stops there; wiring job
 * state in is left to whichever future task gives the workbench a shared "active job" concept.
 *
 * The demo/auto-expire indicator is a compact, static hint — unlike the full `DemoBanner` (which
 * reads the live `/v1/limits` cap), the status bar only needs to say a session is ephemeral, so it
 * adds no query of its own. Gated on `NEXT_PUBLIC_DEMO_BANNER`, exactly like `DemoBanner`; a
 * self-hosted instance renders neither.
 */

/** Extracts the active `file_id` from a `/f/<id>/...` pathname, or `null` off that route — the
 *  same shape as `Toolbar`'s and `WorkbenchLayout`'s own `activeFileIdFrom` helpers, kept local to
 *  each caller since none of the three import from another. */
function activeFileIdFrom(pathname: string | null): string | null {
  if (!pathname) return null;
  const match = pathname.match(/^\/f\/([^/]+)/);
  return match ? match[1] : null;
}

function DemoIndicator() {
  const enabled = process.env.NEXT_PUBLIC_DEMO_BANNER === "1";
  if (!enabled) return null;
  return (
    <span data-testid="statusbar-demo-indicator" className="shrink-0 text-faint">
      Demo · session auto-expires
    </span>
  );
}

/** The file · format · atoms · frames facts, for the active file. Loading/error are rendered
 *  honestly (matching `Inspector`'s own `InspectionSummary` fallbacks) rather than a silent blank. */
function FileFacts({ fileId }: { fileId: string }) {
  const inspection = useInspection(fileId);

  if (inspection.status === "loading") {
    return (
      <span role="status" className="truncate text-muted">
        Inspecting…
      </span>
    );
  }
  if (inspection.status === "error") {
    return <span className="truncate text-muted">Inspection unavailable.</span>;
  }

  const { report } = inspection;
  return (
    <span data-testid="statusbar-facts" className="flex min-w-0 items-center gap-2 truncate">
      <span className="truncate">{report.file.filename}</span>
      <span aria-hidden="true" className="text-faint">
        ·
      </span>
      <span className="truncate">{report.format.format_name}</span>
      <span aria-hidden="true" className="text-faint">
        ·
      </span>
      <span>
        <span data-testid="statusbar-atom-count" className="font-mono text-strong">
          {report.structure.atom_count}
        </span>{" "}
        atoms
      </span>
      <span aria-hidden="true" className="text-faint">
        ·
      </span>
      <span>
        <span data-testid="statusbar-frame-count" className="font-mono text-strong">
          {report.structure.frame_count}
        </span>{" "}
        frames
      </span>
    </span>
  );
}

export function StatusBar() {
  const pathname = usePathname();
  const fileId = activeFileIdFrom(pathname);

  return (
    <footer
      role="contentinfo"
      className="flex h-8 items-center justify-between gap-4 border-t border-wb-hairline bg-wb-status px-4 text-xs text-muted"
    >
      <span className="sr-only">Status bar</span>
      {fileId ? (
        <FileFacts fileId={fileId} />
      ) : (
        <span data-testid="statusbar-ready">Ready</span>
      )}
      <DemoIndicator />
    </footer>
  );
}
