import type { ReactNode } from "react";
import { StatusBar } from "@/components/shell/StatusBar";
import { Inspector } from "@/components/shell/Inspector";
import { Toolbar } from "@/components/shell/Toolbar";

/**
 * The workbench shell (v2.0 addendums, Task 7; design spec §"Shell architecture").
 *
 * A full-viewport CSS grid — toolbar (row 1, full width), then a middle row of
 * `[sources rail | center | inspector]`, then the status bar (row 3, full width). `{children}`
 * (the routed page) renders into the center region, which carries the `#main-content` skip-link
 * target that used to live directly in `app/layout.tsx`.
 *
 * This is the *scaffold* slice: the sources rail is a temporary stand-in (see the inline notes
 * below), and the inspector/status bar are minimal stubs (`Inspector.tsx`, `StatusBar.tsx`). The
 * toolbar is the real `Toolbar` component (Task 8). Real content for the remaining regions lands
 * in Tasks 9–11.
 */
export function WorkbenchLayout({ children }: { children: ReactNode }) {
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
      <div className="grid grid-cols-[auto_1fr_auto] overflow-hidden">
        {/* Sources rail — middle-left, an empty placeholder column ONLY (no label, no landmark).
            `app/f/[file_id]/layout.tsx` already renders the real, populated `<SourceRail
            fileId=.../>` (an `<aside aria-label="Source file">`) inline as part of `{children}`,
            which now renders inside this shell's center — so this column must not carry its own
            "Sources" heading/landmark, or every `/f/[file_id]/*` page would show two competing
            Sources panels. It exists only to reserve the rail's width/chrome for non-file routes
            (`/formats`, `/history`, `/docs`) until Task 9 gives it real content.
            TODO(Task 9): move the real SourceRail into this slot and remove it from
            f/[file_id]/layout.tsx. */}
        <div
          data-testid="wb-sources-placeholder"
          className="hidden w-56 shrink-0 border-r border-wb-hairline bg-wb-rail md:block"
        />

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

        {/* Inspector — middle-right (Task 10 stub). */}
        <Inspector />
      </div>

      {/* Status bar — row 3, full width (Task 11 stub). */}
      <StatusBar />
    </div>
  );
}
