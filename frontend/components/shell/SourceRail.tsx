"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { historyInfiniteQuery } from "@/lib/api/queries";
import type { HistoryItem } from "@/lib/history/status";
import { listRecents, mergeRecents, MAX_RECENTS, type RecentFile } from "@/lib/prefs/recents";

/**
 * The workbench Sources rail (v2.0 addendums, Task 9; design spec §"Shell architecture" — Sources
 * rail row: "Session files with format badges; drop-to-add; collapsible").
 *
 * Lives once, in `WorkbenchLayout`'s middle-left slot (replacing the Task 7 empty placeholder;
 * `WorkbenchLayout.tsx`'s `TODO(Task 9)`), as a **persistent, cross-route** shell region — not a
 * per-file panel. It shares its data source with `RecentsStrip`
 * (`components/history/RecentsStrip.tsx`): this browser's localStorage recents merged with the
 * durable `/v1/history` list (`lib/prefs/recents.ts`), so a file shows up here the moment it's
 * opened or converted, on every route, with no second backend call (the D-R6 precedent
 * `RecentsStrip` already established). Only entries that still have a live `file_id` are listed —
 * this rail is "session files" (things you can still open a workspace for), not the full durable
 * history (`/history` already covers records whose bytes have expired).
 *
 * `WorkbenchLayout` derives `activeFileId` from the route (`/f/<id>/...`, mirroring the `Toolbar`'s
 * own `activeFileIdFrom` helper) and owns the persisted `collapsed` boolean — this component is
 * presentational over those two pieces of state plus its own query.
 *
 * Drop-to-add: full drag-and-drop wiring (a dedicated drop zone + upload submission living in the
 * rail) was judged out of proportion for this slice, so the affordance is a plain "+ Add file" link
 * to `/`, where the existing landing dropzone already handles both click-to-browse and drag-drop.
 *
 * Reconciliation note (Task 9): this file used to be the *per-file* pinned rail that
 * `app/f/[file_id]/layout.tsx` rendered inline (filename, detected format + confidence, frame/atom/
 * size counts, the guided "Convert →" CTA, "Upload another file") — evolved in place rather than
 * left as a second, dead component. That content is not silently dropped: Open/Upload and Convert
 * now live in the `Toolbar` (Task 8), and the remaining per-file facts (format + confidence, counts)
 * are exactly the Inspector's stated job ("summary chips ... [Report]; atom/cell props ...
 * [Structure]", design spec §"Shell architecture") — flagged explicitly for Task 10 in the Task 9
 * report rather than assumed.
 */
function historyToRecent(item: HistoryItem): RecentFile | null {
  const source = item.source as { format_id?: unknown; filename?: unknown };
  const fileId = typeof item.file_id === "string" ? item.file_id : null;
  // Only a live upload has a workspace to link into — an expired-bytes record belongs to /history,
  // not the "session files" rail.
  if (!fileId) return null;
  const formatId = typeof source.format_id === "string" ? source.format_id : "";
  const filename = typeof source.filename === "string" ? source.filename : item.conversion_id;
  return {
    key: fileId,
    href: `/f/${fileId}`,
    filename,
    format_id: formatId,
    last_seen_at: item.created_at,
  };
}

/** The id the collapse toggle's `aria-controls` points at — the WAI-ARIA disclosure pattern's
 * controlled region, whichever of the two mutually-exclusive branches (empty state or file list)
 * is currently rendered. */
const RAIL_CONTENT_ID = "source-rail-content";

function railRowClass(active: boolean): string {
  return `flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
    active ? "bg-well text-strong" : "text-body hover:bg-well/60"
  }`;
}

export function SourceRail({
  activeFileId,
  collapsed,
  onToggle,
}: {
  activeFileId: string | null;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { data } = useInfiniteQuery(historyInfiniteQuery(MAX_RECENTS));
  const seeded = useMemo(
    () =>
      (data?.pages[0]?.items ?? [])
        .map(historyToRecent)
        .filter((r): r is RecentFile => r !== null),
    [data],
  );
  // The persisted recents are read once — the rail is a snapshot of "recent", not a live counter
  // (same rule as RecentsStrip).
  const persisted = useMemo(() => listRecents(), []);
  const files = useMemo(() => mergeRecents(persisted, seeded), [persisted, seeded]);

  return (
    <nav
      aria-label="Sources"
      className={`hidden shrink-0 flex-col border-r border-wb-hairline bg-wb-rail md:flex ${
        collapsed ? "w-12" : "w-56"
      }`}
    >
      <div className="flex items-center justify-between gap-2 p-2">
        {collapsed ? null : (
          <h2 className="text-xs font-semibold uppercase tracking-wide text-faint">Sources</h2>
        )}
        <button
          type="button"
          aria-expanded={!collapsed}
          aria-controls={RAIL_CONTENT_ID}
          aria-label={collapsed ? "Expand sources rail" : "Collapse sources rail"}
          onClick={onToggle}
          className="ml-auto rounded-sm px-1.5 py-1 text-sm text-faint transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {collapsed ? "»" : "«"}
        </button>
      </div>

      {collapsed ? null : files.length === 0 ? (
        <div id={RAIL_CONTENT_ID} className="space-y-2 p-3 text-sm text-muted">
          <p>No files yet. Drop one to begin.</p>
          <Link
            href="/"
            className="inline-block text-body underline underline-offset-2 hover:text-strong"
          >
            + Add file
          </Link>
        </div>
      ) : (
        <ul
          id={RAIL_CONTENT_ID}
          className="flex-1 space-y-0.5 overflow-y-auto p-2"
          data-testid="source-rail-list"
        >
          {files.map((file) => {
            const active = file.key === activeFileId;
            return (
              <li key={file.key}>
                <Link
                  href={file.href}
                  aria-current={active ? "page" : undefined}
                  className={railRowClass(active)}
                >
                  <span className="min-w-0 flex-1 truncate">{file.filename}</span>
                  {file.format_id ? (
                    <span className="shrink-0 rounded bg-well px-1 py-0.5 font-mono text-[0.65rem] uppercase text-muted">
                      {file.format_id}
                    </span>
                  ) : null}
                </Link>
              </li>
            );
          })}
          <li>
            <Link
              href="/"
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted underline underline-offset-2 hover:text-strong"
            >
              + Add file
            </Link>
          </li>
        </ul>
      )}
    </nav>
  );
}
