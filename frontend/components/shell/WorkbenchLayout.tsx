"use client";

import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { StatusBar } from "@/components/shell/StatusBar";
import { Inspector } from "@/components/shell/Inspector";
import { Toolbar } from "@/components/shell/Toolbar";
import { SourceRail } from "@/components/shell/SourceRail";
import { readJson, writeJson } from "@/lib/prefs/storage";

/** The persisted Sources-rail collapse preference (a per-viewer QoL pref, like the theme). */
const RAIL_COLLAPSED_KEY = "sources-rail-collapsed";

function isBoolean(v: unknown): v is boolean {
  return typeof v === "boolean";
}

/** Extracts the active `file_id` from a `/f/<id>/...` pathname, or `null` off that route — the
 * same shape as `Toolbar`'s own `activeFileIdFrom` helper, kept local to each caller rather than
 * shared, since neither imports the other. */
function activeFileIdFrom(pathname: string | null): string | null {
  if (!pathname) return null;
  const match = pathname.match(/^\/f\/([^/]+)/);
  return match ? match[1] : null;
}

/**
 * The workbench shell (v2.0 addendums, Task 7; design spec §"Shell architecture").
 *
 * A full-viewport CSS grid — toolbar (row 1, full width), then a middle row of
 * `[sources rail | center | inspector]`, then the status bar (row 3, full width). `{children}`
 * (the routed page) renders into the center region, which carries the `#main-content` skip-link
 * target that used to live directly in `app/layout.tsx`.
 *
 * The sources rail is now the real, persistent `SourceRail` (Task 9) — it lives here once, for
 * every route, rather than being re-rendered per `/f/[file_id]` page. This component owns the two
 * pieces of state `SourceRail` is presentational over: the active file id (derived from the route)
 * and the collapsed flag (persisted like the app's other per-viewer prefs, e.g. the theme). The
 * inspector (`Inspector.tsx`, Task 10) and status bar (`StatusBar.tsx`, Task 11) are now both real,
 * self-contained components — like `SourceRail`, neither takes props from here; each derives its
 * own route context from `usePathname()`.
 */
export function WorkbenchLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const activeFileId = activeFileIdFrom(pathname);
  const [collapsed, setCollapsed] = useState(false);

  // Hydrate the persisted preference after mount only — SSR has no localStorage, so the first
  // render always assumes expanded, then syncs to whatever this browser last chose.
  useEffect(() => {
    setCollapsed(readJson(RAIL_COLLAPSED_KEY, isBoolean, false));
  }, []);

  const handleToggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      writeJson(RAIL_COLLAPSED_KEY, next);
      return next;
    });
  }, []);

  return (
    // min-h-screen, not h-screen: `app/layout.tsx` renders `DemoBanner` as an in-flow sibling
    // ABOVE this shell when NEXT_PUBLIC_DEMO_BANNER is set (the hosted demo), so a fixed h-screen
    // here would push the shell's own height past the viewport and clip StatusBar (row 3) below
    // the fold. min-h-screen lets the grid grow to fit banner + content instead, so the status bar
    // always sits right after real content. Trade-off: on a very tall page the status bar no
    // longer clings to the bottom of the *viewport* the way a fixed h-screen would — it sits at
    // the bottom of the *document* instead. A true always-visible (sticky) status bar is left to
    // Task 11/13 once it has real content to justify the complexity.
    <div className="grid min-h-screen grid-rows-[auto_1fr_auto]">
      {/* Toolbar — row 1, full width. Toolbar renders its own `<header>` (the workbench's single
          `banner` landmark), painted with the workbench chrome tokens
          (`bg-wb-toolbar` / `border-wb-hairline`) directly — no extra chrome layered here. */}
      <Toolbar />

      {/* Middle row: sources rail | center | inspector. */}
      {/* `min-w-0`: this is also a row of the root grid above (`grid-rows-[auto_1fr_auto]`) — see
          `StatusBar.tsx`'s footer for why every row needs this. */}
      <div className="grid min-w-0 grid-cols-[auto_1fr_auto] overflow-hidden">
        {/* Sources rail — middle-left, the real persistent SourceRail (Task 9). It used to be a
            reserved-but-empty placeholder column here while `app/f/[file_id]/layout.tsx` rendered
            its own per-file `<SourceRail fileId=.../>` inline; that duplicate has been removed
            (see that layout file) so the "Sources" landmark exists exactly once, for every route. */}
        <SourceRail activeFileId={activeFileId} collapsed={collapsed} onToggle={handleToggle} />

        {/* Center — the only region that swaps per routed page. Carries the skip-link target
            moved here from app/layout.tsx. */}
        <main
          id="main-content"
          tabIndex={-1}
          role="main"
          className="overflow-y-auto focus:outline-none"
        >
          <div className="mx-auto max-w-5xl px-4 py-8">{children}</div>
        </main>

        {/* Inspector — middle-right, the real contextual panel (Task 10). */}
        <Inspector />
      </div>

      {/* Status bar — row 3, full width. */}
      <StatusBar />
    </div>
  );
}
