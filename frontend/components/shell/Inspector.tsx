"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
/** The id the mobile-open toggle's `aria-controls` points at — the Inspector's own `aside` landmark
 * (design spec §"Region behaviors & responsiveness": "hidden behind toggles" below `lg`). */
const INSPECTOR_ASIDE_ID = "inspector-aside";

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
      <Provenance record={record} dense />

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
  // Below `lg` the Inspector has no room beside the center — it is hidden behind a toggle rather
  // than simply gone (design spec §"Region behaviors & responsiveness"), same pattern as the
  // Sources rail's `mobileOpen` (SourceRail.tsx): a separate, ephemeral per-viewport flag from the
  // persisted desktop `collapsed` icon-rail preference.
  const [mobileOpen, setMobileOpen] = useState(false);

  // Escape closes the overlay from anywhere on the page — same global-listener pattern as
  // SourceRail's mobile toggle (see its comment): the button that opens the `aside` lives outside
  // it, so a keydown handler on the `aside` alone would never see the key while focus is still on
  // that toggle.
  useEffect(() => {
    if (!mobileOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  // Keyboard focus management for the split disclosure toggle — same rationale as SourceRail: the
  // FAB and the in-drawer ✕ unmount/mount on each transition, so without this the activated element
  // is destroyed and focus falls to `<body>`. On open, focus the drawer's close button; on close,
  // return focus to the FAB. `prevOpen` gates it to real transitions so mount never steals focus.
  const fabRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const prevOpen = useRef(mobileOpen);
  useEffect(() => {
    if (prevOpen.current !== mobileOpen) {
      (mobileOpen ? closeRef : fabRef).current?.focus();
      prevOpen.current = mobileOpen;
    }
  }, [mobileOpen]);

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
    <>
      {/* The reachable open control for the hidden-below-lg Inspector — the "show" half of a split
          disclosure toggle (the "hide" half is the ✕ inside the aside below), the same pattern as
          SourceRail's mobile toggle: one control present at a time, so the open overlay (`z-40`)
          never covers the "hide" toggle. Rendered outside the `aside` so it stays in the layout (and
          the a11y tree) while the aside is `hidden`. `lg:hidden` because at `lg`+ the Inspector is
          always present and this would be redundant with its own collapse/expand control.
          `bottom-20`, matching SourceRail's toggle on the opposite corner, keeps the two toggles at
          the same height as a predictable, symmetric target. */}
      {mobileOpen ? null : (
        <button
          ref={fabRef}
          type="button"
          aria-expanded={false}
          aria-controls={INSPECTOR_ASIDE_ID}
          aria-label="Show inspector"
          onClick={() => setMobileOpen(true)}
          className="fixed bottom-20 right-4 z-30 rounded-full border border-wb-hairline bg-wb-panel px-3 py-2 text-xs font-medium text-body shadow-lg transition-colors hover:bg-well focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent lg:hidden"
        >
          Inspector
        </button>
      )}
      {/* Backdrop: dismisses the overlay on an outside click/tap. Decorative — the toggle button
          above and the global Escape listener are the real dismiss affordances. */}
      {mobileOpen ? (
        <div
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
        />
      ) : null}
      <aside
        id={INSPECTOR_ASIDE_ID}
        aria-label="Inspector"
        role="complementary"
        className={`${
          mobileOpen ? "flex fixed inset-y-0 right-0 z-40 w-72 shadow-xl" : "hidden"
        } shrink-0 flex-col border-l border-wb-hairline bg-wb-panel lg:static lg:z-auto lg:flex lg:shadow-none ${
          collapsed ? "lg:w-12" : "lg:w-72"
        }`}
      >
        {mobileOpen ? (
          // The "hide" half of the split disclosure toggle: shown only while the overlay is open, on
          // top of it (so it is always clickable, unlike a bottom-right FAB the overlay would cover).
          // It carries the same `aria-expanded`/`aria-controls` as the FAB, so screen readers and the
          // responsive e2e both see exactly one "Show inspector"/"Hide inspector" control at any
          // moment (v2.0 addendums Task 13).
          <div className="flex justify-end p-2 lg:hidden">
            <button
              ref={closeRef}
              type="button"
              aria-expanded={true}
              aria-controls={INSPECTOR_ASIDE_ID}
              aria-label="Hide inspector"
              onClick={() => setMobileOpen(false)}
              className="rounded-sm px-1.5 py-1 text-sm text-faint transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              ✕
            </button>
          </div>
        ) : null}
        {/* `collapsed` is the persisted *desktop* icon-rail preference and must never blank the mobile
            overlay: the heading and content honour it only when the drawer is closed
            (`collapsed && !mobileOpen`), and the collapse toggle is `hidden lg:inline-flex` —
            desktop-only — so it cannot be tapped inside the open drawer to empty it (Task 13 review
            fix; mirrors SourceRail). */}
        <div className="flex items-center justify-between gap-2 px-4 py-2">
          {collapsed && !mobileOpen ? null : (
            <h2 className="text-xs font-semibold uppercase tracking-wide text-faint">Inspector</h2>
          )}
          <button
            type="button"
            aria-expanded={!collapsed}
            aria-controls={INSPECTOR_CONTENT_ID}
            aria-label={collapsed ? "Expand inspector" : "Collapse inspector"}
            onClick={handleToggle}
            className="ml-auto hidden rounded-sm px-1.5 py-1 text-sm text-faint transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent lg:inline-flex"
          >
            {collapsed ? "«" : "»"}
          </button>
        </div>

        {collapsed && !mobileOpen ? null : (
          // `tabIndex={0}`: this is an `overflow-y-auto` scroll container, and on some tabs (e.g.
          // Compare) its content has no focusable descendants of its own, so a keyboard-only user
          // could not scroll it — axe's `scrollable-region-focusable` (WCAG 2.1.1) flags exactly
          // that. Making the region itself focusable is the canonical fix (v2.0 addendums Task 13).
          <div
            id={INSPECTOR_CONTENT_ID}
            tabIndex={0}
            className="flex-1 space-y-3 overflow-y-auto px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
          >
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
    </>
  );
}
