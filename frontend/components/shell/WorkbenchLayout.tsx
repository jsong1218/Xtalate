import type { ReactNode } from "react";
import { AppHeader } from "@/components/shell/AppHeader";
import { StatusBar } from "@/components/shell/StatusBar";
import { Inspector } from "@/components/shell/Inspector";

/**
 * The workbench shell (v2.0 addendums, Task 7; design spec §"Shell architecture").
 *
 * A full-viewport CSS grid — toolbar (row 1, full width), then a middle row of
 * `[sources rail | center | inspector]`, then the status bar (row 3, full width). `{children}`
 * (the routed page) renders into the center region, which carries the `#main-content` skip-link
 * target that used to live directly in `app/layout.tsx`.
 *
 * This is the *scaffold* slice: the toolbar and sources rail are temporary stand-ins (see the
 * inline notes below), and the inspector/status bar are minimal stubs (`Inspector.tsx`,
 * `StatusBar.tsx`). Real content for each region lands in Tasks 8–11; this task only makes the
 * five-region grid real and wires the skip-link target through it.
 */
export function WorkbenchLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid h-screen grid-rows-[auto_1fr_auto]">
      {/* Toolbar — row 1, full width. */}
      {/* TODO(Task 8): replace AppHeader with Toolbar. AppHeader already renders its own
          `border-b border-line` banner chrome, so no extra wb-toolbar background/border is
          layered here to avoid a double border; Task 8's real Toolbar picks up bg-wb-toolbar /
          border-wb-hairline directly. */}
      <AppHeader />

      {/* Middle row: sources rail | center | inspector. */}
      <div className="grid grid-cols-[auto_1fr_auto] overflow-hidden">
        {/* Sources rail — middle-left. SourceRail (Task 9's real content) requires a `fileId`
            prop that the shell doesn't have (it wraps every route, including non-file pages like
            `/formats`/`/history`/`/docs`), so this is a minimal placeholder until Task 9 wires
            per-file selection and collapsibility. */}
        <div
          role="region"
          aria-label="Sources"
          className="hidden w-56 shrink-0 border-r border-wb-hairline bg-wb-rail p-4 md:block"
        >
          <h2 className="text-sm font-semibold text-strong">Sources</h2>
        </div>

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
