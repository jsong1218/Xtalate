"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
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

/** The id the mobile-open toggle's `aria-controls` points at — the rail's own `nav` landmark
 * (design spec §"Region behaviors & responsiveness": "hidden behind toggles" below `md`). */
const RAIL_NAV_ID = "source-rail-nav";

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

  // Below `md` the rail has no room beside the center — it is hidden behind a toggle rather than
  // simply gone (design spec §"Region behaviors & responsiveness"). This is a separate, ephemeral
  // per-viewport flag from `collapsed` (the persisted desktop icon-rail preference): a phone user
  // never has a "collapsed" rail, they have a closed one they can open as a temporary overlay.
  const [mobileOpen, setMobileOpen] = useState(false);

  // Escape closes the overlay from anywhere on the page (not only while focus sits inside the
  // `nav`) — the toggle button that opens it lives outside the `nav` it controls, so a keydown
  // handler on the `nav` alone would never see the key while focus is still on that toggle
  // (matching the `CommandPaletteTrigger` global-listener pattern already used in this shell).
  useEffect(() => {
    if (!mobileOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  // Keyboard focus management for the split disclosure toggle. Its two halves (the FAB that opens,
  // the in-drawer ✕ that closes) are separate nodes that mount/unmount on each transition, so the
  // element the user just activated is destroyed on the next render and the browser drops focus to
  // `<body>` — a keyboard user loses their place and must re-Tab. So on open, move focus into the
  // drawer (its close button); on close, return it to the FAB (the trigger). `prevOpen` gates this
  // to real transitions, so it never steals focus on the initial mount.
  const fabRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const prevOpen = useRef(mobileOpen);
  useEffect(() => {
    if (prevOpen.current !== mobileOpen) {
      (mobileOpen ? closeRef : fabRef).current?.focus();
      prevOpen.current = mobileOpen;
    }
  }, [mobileOpen]);

  return (
    <>
      {/* The reachable open control for the hidden-below-md rail — the "show" half of a split
          disclosure toggle (the "hide" half is the ✕ inside the drawer below). One control is
          present at a time: this FAB while the rail is closed, the in-drawer ✕ while it is open.
          They are split rather than a single always-on FAB because the open drawer (`z-40`, full
          height on the left) would cover a bottom-left FAB, leaving the "hide" toggle unclickable —
          so the close control lives inside the drawer, on top, instead. Rendered outside the `nav`
          so it stays in the layout (and the a11y tree) while the rail it controls is `hidden`.
          `md:hidden` because at `md`+ the rail is always present and this would be redundant with
          the rail's own collapse/expand control. `bottom-20` rather than the tighter `bottom-4`:
          Next.js's dev-mode indicator (a fixed ~32px pill in the bottom-left corner, `next dev`
          only — never in a production build) sits almost exactly where `bottom-4 left-4` would,
          intercepting pointer events; the extra clearance keeps this reachable under both `next
          dev` (what the Docker e2e stack runs) and a production self-host. */}
      {mobileOpen ? null : (
        <button
          ref={fabRef}
          type="button"
          aria-expanded={false}
          aria-controls={RAIL_NAV_ID}
          aria-label="Show sources"
          onClick={() => setMobileOpen(true)}
          className="fixed bottom-20 left-4 z-30 rounded-full border border-wb-hairline bg-wb-rail px-3 py-2 text-xs font-medium text-body shadow-lg transition-colors hover:bg-well focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent md:hidden"
        >
          Sources
        </button>
      )}
      {/* Backdrop: dismisses the overlay on an outside click/tap. Decorative — the toggle button
          above and the global Escape listener are the real dismiss affordances. */}
      {mobileOpen ? (
        <div
          aria-hidden="true"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
        />
      ) : null}
      <nav
        id={RAIL_NAV_ID}
        aria-label="Sources"
        className={`${
          mobileOpen ? "flex fixed inset-y-0 left-0 z-40 w-64 shadow-xl" : "hidden"
        } shrink-0 flex-col border-r border-wb-hairline bg-wb-rail md:static md:z-auto md:flex md:shadow-none ${
          collapsed ? "md:w-12" : "md:w-56"
        }`}
      >
        {mobileOpen ? (
          // The "hide" half of the split disclosure toggle: shown only while the drawer is open, on
          // top of it (so it is always clickable, unlike a bottom-left FAB the drawer would cover).
          // It carries the same `aria-expanded`/`aria-controls` as the FAB, so screen readers and the
          // responsive e2e both see exactly one "Show sources"/"Hide sources" control at any moment
          // (v2.0 addendums Task 13).
          <div className="flex justify-end p-2 md:hidden">
            <button
              ref={closeRef}
              type="button"
              aria-expanded={true}
              aria-controls={RAIL_NAV_ID}
              aria-label="Hide sources"
              onClick={() => setMobileOpen(false)}
              className="rounded-sm px-1.5 py-1 text-sm text-faint transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              ✕
            </button>
          </div>
        ) : null}
      {/* `collapsed` is the persisted *desktop* icon-rail preference; it must never blank the mobile
          overlay, which has no icon-rail form. So the heading and content below honour it only when
          the drawer is not open (`collapsed && !mobileOpen`), and the collapse toggle itself is
          `hidden md:inline-flex` — desktop-only — so it cannot be tapped inside the open drawer to
          empty it (v2.0 addendums Task 13, review fix). */}
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        {collapsed && !mobileOpen ? null : (
          <h2 className="text-xs font-semibold uppercase tracking-wide text-faint">Sources</h2>
        )}
        <button
          type="button"
          aria-expanded={!collapsed}
          aria-controls={RAIL_CONTENT_ID}
          aria-label={collapsed ? "Expand sources rail" : "Collapse sources rail"}
          onClick={onToggle}
          className="ml-auto hidden rounded-sm px-1.5 py-1 text-sm text-faint transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent md:inline-flex"
        >
          {collapsed ? "»" : "«"}
        </button>
      </div>

      {collapsed && !mobileOpen ? null : files.length === 0 ? (
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
          className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2"
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
    </>
  );
}
