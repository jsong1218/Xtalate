"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Provenance } from "@/components/Provenance";
import { SummaryChips } from "@/components/report/SummaryChips";
import { StructureLegend } from "@/components/StructureLegend";
import { DataValue } from "@/components/ui/DataValue";
import { conversionQuery } from "@/lib/api/queries";
import { useInspection } from "@/lib/api/useInspection";
import { useConversionGeometry, useFileGeometry } from "@/lib/geometry/useGeometry";
import { readJson, writeJson } from "@/lib/prefs/storage";
import type { ConversionRecord as ConversionRecordModel } from "@/lib/report/types";

/**
 * The workbench inspector rail (right side of `WorkbenchLayout`, design spec §"Shell architecture" —
 * Inspector row: "Contextual: summary chips + cell + provenance (Report); atom/cell props + legend
 * (Structure); collapsible").
 *
 * Task 7 stubbed this as a bare landmark; this task fills it in. It derives both the active file id
 * and which workspace tab is showing from `usePathname()` (mirroring `Toolbar`/`WorkbenchLayout`'s own
 * `activeFileIdFrom` helper) rather than taking props — `WorkbenchLayout` renders `<Inspector/>` with
 * no arguments, matching how `Toolbar` already derives its own route context internally.
 *
 * **The always-on content: the inspection summary.** `SourceRail.tsx`'s reconciliation note flags
 * this explicitly: the pre-Task-9 per-file rail rendered inline by `app/f/[file_id]/layout.tsx` used
 * to show the file's filename, detected format + confidence, and its field accounting, sourced from
 * the same `useInspection(fileId)` hook the Inspect tab renders. That content is not silently
 * dropped — it is exactly this panel's must-have job, on every `/f/<id>/...` route.
 *
 * **Route-specific enrichment** layers on top, reusing existing hooks/components rather than
 * inventing new fetching:
 *   - **Report route** (`/f/<id>/report/<conversion_id>`) — `SummaryChips` + the conversion's output
 *     cell + `Provenance`, read from the *same* `conversionQuery` the Report tab's own
 *     `ConversionRecord` reads (react-query dedupes the identical key) and the *same*
 *     `useConversionGeometry` hook that page's Structure/Compare viewers already call.
 *   - **Structure route** (`/f/<id>/structure`) — atom/cell props + `StructureLegend`, read from the
 *     *same* `useFileGeometry` hook that tab's own `StructureTab` already calls.
 *   - Any other `/f/<id>/...` route (Inspect, Convert, Analysis) shows the inspection summary alone;
 *     inventing enrichment for those tabs was judged out of proportion for this slice.
 *
 * Off a `/f/<id>` route entirely (the landing page, `/formats`, `/history`, `/docs`) — or before a
 * file id resolves — the panel renders nothing meaningful below its heading, never a stale summary
 * from whichever file was last active. It stays a permanent `complementary` landmark either way
 * (`WorkbenchLayout` always mounts it), distinct from the Sources rail's `navigation` landmark.
 */

const INSPECTOR_COLLAPSED_KEY = "inspector-collapsed";
const INSPECTOR_CONTENT_ID = "inspector-content";

function isBoolean(v: unknown): v is boolean {
  return typeof v === "boolean";
}

/** The route contexts the Inspector recognizes, mirroring `Toolbar`'s `activeFileIdFrom` helper but
 *  additionally naming which route-specific enrichment (if any) applies. */
type InspectorContext =
  | { kind: "none" }
  | { kind: "report"; fileId: string; conversionId: string }
  | { kind: "structure"; fileId: string }
  | { kind: "other"; fileId: string };

function contextFromPathname(pathname: string | null): InspectorContext {
  if (!pathname) return { kind: "none" };
  const fileMatch = pathname.match(/^\/f\/([^/]+)/);
  if (!fileMatch) return { kind: "none" };
  const fileId = fileMatch[1];
  const reportMatch = pathname.match(/^\/f\/[^/]+\/report\/([^/]+)/);
  if (reportMatch) return { kind: "report", fileId, conversionId: reportMatch[1] };
  if (/^\/f\/[^/]+\/structure(?:\/|$)/.test(pathname)) return { kind: "structure", fileId };
  return { kind: "other", fileId };
}

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/** A cell's lattice vectors, or the honest "no cell" caption `StructureViewer` already uses (P3:
 *  cell-less is a fact, never drawn as a fabricated box). Shared by both route enrichments so the
 *  wording never drifts between the Report and Structure panels. */
function CellSummary({ cell }: { cell: number[][] | null | undefined }) {
  if (!cell) {
    return (
      <p data-testid="inspector-no-cell" className="text-xs text-muted">
        This file declares no simulation cell.
      </p>
    );
  }
  return (
    <div data-testid="inspector-cell" className="space-y-0.5">
      <p className="text-xs font-semibold text-body">Cell (Å)</p>
      {cell.map((row, i) => (
        <DataValue key={i} className="block text-xs">
          {row.map((v) => v.toFixed(3)).join(", ")}
        </DataValue>
      ))}
    </div>
  );
}

/**
 * The always-on inspection summary (absorbed from the pre-Task-9 per-file rail — see the module
 * docstring). Loading/error states are rendered honestly rather than a silent blank, matching the
 * old rail's own fallbacks.
 */
function InspectionSummary({ fileId }: { fileId: string }) {
  const inspection = useInspection(fileId);

  if (inspection.status === "loading") {
    return (
      <p role="status" className="text-sm text-muted">
        Inspecting…
      </p>
    );
  }
  if (inspection.status === "error") {
    return <p className="text-sm text-muted">Inspection unavailable.</p>;
  }

  const { report } = inspection;
  const present = report.fields.filter(
    (field) => field.status === "present" || field.status === "mixed",
  ).length;
  const absent = report.fields.length - present;

  return (
    <div data-testid="inspector-summary" className="space-y-2">
      <div className="space-y-0.5">
        <p className="break-all text-sm font-semibold text-strong">{report.file.filename}</p>
        <p className="text-xs text-body">
          {report.format.format_name}{" "}
          <span className="text-faint">({percent(report.format.confidence)} confidence)</span>
        </p>
      </div>
      <dl className="space-y-1 text-xs">
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Fields present</dt>
          <dd data-testid="fields-present-count">
            <DataValue>{present}</DataValue>
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Fields absent</dt>
          <dd data-testid="fields-absent-count">
            <DataValue>{absent}</DataValue>
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** Report-route enrichment: SummaryChips + cell + Provenance, reusing the Report tab's own hooks. */
function ReportEnrichment({ conversionId }: { conversionId: string }) {
  const query = useQuery(conversionQuery(conversionId));
  const geometry = useConversionGeometry(conversionId, "output");
  const record = query.data as ConversionRecordModel | undefined;
  if (!record) return null;

  const report = record.conversion_report;
  // A refusal has no output — nothing to summarize, no cell, no viewer (ConversionRecord follows
  // the same rule for its own Structure/Compare tabs).
  if (report.status === "refused") return null;

  return (
    <div data-testid="inspector-report" className="space-y-3 border-t border-wb-hairline pt-3">
      <SummaryChips report={report} />
      {geometry.status === "ready" ? <CellSummary cell={geometry.geometry?.cell} /> : null}
      <Provenance record={record} />
    </div>
  );
}

/** Structure-route enrichment: atom/cell props + StructureLegend, reusing the Structure tab's hook. */
function StructureEnrichment({ fileId }: { fileId: string }) {
  const geometry = useFileGeometry(fileId);
  if (geometry.status !== "ready" || !geometry.geometry) return null;

  const { species, cell, frame_count } = geometry.geometry;
  return (
    <div data-testid="inspector-structure" className="space-y-3 border-t border-wb-hairline pt-3">
      <dl className="space-y-1 text-xs">
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Atoms</dt>
          <dd>
            <DataValue>{species.length}</DataValue>
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Frames</dt>
          <dd>
            <DataValue>{frame_count}</DataValue>
          </dd>
        </div>
      </dl>
      <CellSummary cell={cell} />
      <StructureLegend species={species} />
    </div>
  );
}

export function Inspector() {
  const pathname = usePathname();
  const context = useMemo(() => contextFromPathname(pathname), [pathname]);
  const [collapsed, setCollapsed] = useState(false);

  // Hydrate the persisted preference after mount only — SSR has no localStorage (same pattern as
  // WorkbenchLayout's own Sources-rail collapse preference).
  useEffect(() => {
    setCollapsed(readJson(INSPECTOR_COLLAPSED_KEY, isBoolean, false));
  }, []);

  function handleToggle() {
    setCollapsed((prev) => {
      const next = !prev;
      writeJson(INSPECTOR_COLLAPSED_KEY, next);
      return next;
    });
  }

  return (
    <aside
      aria-label="Inspector"
      role="complementary"
      className={`hidden shrink-0 flex-col border-l border-wb-hairline bg-wb-panel lg:flex ${
        collapsed ? "w-12" : "w-72"
      }`}
    >
      <div className="flex items-center justify-between gap-2 p-2">
        {collapsed ? null : (
          <h2 className="text-xs font-semibold uppercase tracking-wide text-faint">Inspector</h2>
        )}
        <button
          type="button"
          aria-expanded={!collapsed}
          aria-controls={INSPECTOR_CONTENT_ID}
          aria-label={collapsed ? "Expand inspector" : "Collapse inspector"}
          onClick={handleToggle}
          className="ml-auto rounded-sm px-1.5 py-1 text-sm text-faint transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {collapsed ? "«" : "»"}
        </button>
      </div>

      {collapsed ? null : (
        <div id={INSPECTOR_CONTENT_ID} className="flex-1 space-y-3 overflow-y-auto p-3">
          {context.kind === "none" ? null : (
            <>
              <InspectionSummary fileId={context.fileId} />
              {context.kind === "report" ? (
                <ReportEnrichment conversionId={context.conversionId} />
              ) : null}
              {context.kind === "structure" ? (
                <StructureEnrichment fileId={context.fileId} />
              ) : null}
            </>
          )}
        </div>
      )}
    </aside>
  );
}
