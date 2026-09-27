"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { CommandPaletteTrigger } from "@/components/command/CommandPaletteTrigger";
import { NotifyToggle } from "@/lib/notify/NotifyPreferenceProvider";
import { ThemeToggle } from "@/lib/theme/ThemeProvider";

/**
 * The workbench toolbar (v2.0 addendums, Task 8; design spec §"Shell architecture" — Toolbar row:
 * brand + verbs on the left, global destinations + toggles on the right).
 *
 * Replaces the temporary `AppHeader` `WorkbenchLayout` rendered from Task 7. Same `<header>`-rooted
 * shape (so it is the workbench's single `banner` landmark — `WorkbenchLayout` places it as the top
 * grid row and adds no competing landmark of its own), now painted with the workbench chrome tokens
 * (`bg-wb-toolbar` / `border-wb-hairline`, Task 6) instead of the page-level `bg-surface`/`border-line`.
 *
 * Left: the Xtalate wordmark (home), then the two cross-workspace verbs (own `aria-label="File
 * actions"` nav landmark):
 *   - **Open / Upload** — always live, points at `/` where the landing dropzone lives (mirrors
 *     `AppHeader`'s pre-existing "Convert redirects to `/`" precedent).
 *   - **Convert** — jumps straight to the active file's convert route (`/f/[file_id]/convert`).
 *     There is no per-file id outside a `/f/[file_id]/*` route, so with no active file this renders
 *     as a disabled `<button>`, never a dead link.
 *
 * Deliberately NOT included as separate verbs: **Validate** and **Repair**. Neither has a route of
 * its own under `app/f/[file_id]/` (only `convert`, `report`, `structure`, `analysis` exist) —
 * validation and repair both happen *inside* the convert flow. Inventing standalone verbs for them
 * here would mean a dead link or reimplementing convert-flow logic in the toolbar; the honest
 * choice is to omit them and let Convert be the one entry point (P1: no UI surface implies a
 * capability that doesn't exist).
 *
 * Right cluster (design spec §"Shell architecture" — global destinations + toggles on the right,
 * not the left verb nav): the ⌘K palette trigger, then the three global destinations
 * (Formats/History/Docs, in their own `aria-label="Primary"` nav landmark — the same label
 * `AppHeader` used for its one nav), then the completion-signal mute toggle, then the theme toggle.
 * Two distinctly-labeled nav landmarks ("File actions" left, "Primary" right) rather than one,
 * since the left verbs and the right destinations are no longer adjacent in the same list — this
 * still keeps the toolbar as a single `banner` with no duplicate *unlabeled* landmark.
 *
 * **Responsive condensing (v2.0 addendums, Task 13; design spec §"Region behaviors &
 * responsiveness"):** below `sm` there is no room for the "File actions" nav's labelled links
 * beside the wordmark, so it is replaced — not merely wrapped — by a single "Menu" overflow
 * button (`aria-haspopup="menu"`) that reveals the same two verbs as `role="menuitem"` entries in a
 * popover. The popover's items are only mounted while open (not CSS-hidden duplicates), so there is
 * never a second same-named "Open / Upload"/"Convert" control in the accessibility tree at once —
 * the `sm:hidden` button and the `hidden sm:flex` nav are mutually exclusive by breakpoint, exactly
 * like `SourceRail`/`Inspector`'s own mobile toggles.
 */

const GLOBAL_DESTINATIONS: { href: string; label: string }[] = [
  { href: "/formats", label: "Formats" },
  { href: "/history", label: "History" },
  { href: "/docs", label: "Docs" },
];

const linkClass =
  "rounded-sm text-muted transition-colors hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-wb-toolbar";

/** Extracts the active `file_id` from a `/f/<id>/...` pathname, or `null` off that route. */
function activeFileIdFrom(pathname: string | null): string | null {
  if (!pathname) return null;
  const match = pathname.match(/^\/f\/([^/]+)/);
  return match ? match[1] : null;
}

export function Toolbar() {
  const pathname = usePathname();
  const fileId = activeFileIdFrom(pathname);
  const convertHref = fileId ? `/f/${fileId}/convert` : null;
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    // `min-w-0`: this header is a row of `WorkbenchLayout`'s single-column root grid
    // (`grid-rows-[auto_1fr_auto]`) — see `StatusBar.tsx`'s footer for the full explanation of why
    // every row needs this to stop a grid item's content-based automatic minimum width from
    // forcing the shared column past a narrow phone's viewport.
    <header className="min-w-0 border-b border-wb-hairline bg-wb-toolbar">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
        {/* Left cluster: brand + the per-file verbs. */}
        <div className="flex min-w-0 items-center gap-x-4">
          <Link
            href="/"
            className="shrink-0 rounded-sm text-lg font-semibold tracking-tight text-strong transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-wb-toolbar"
          >
            Xtalate
          </Link>
          <nav
            aria-label="File actions"
            className="hidden items-center gap-x-4 gap-y-1 text-sm sm:flex sm:flex-wrap"
          >
            <Link href="/" className={linkClass}>
              Open / Upload
            </Link>
            {convertHref ? (
              <Link href={convertHref} className={linkClass}>
                Convert
              </Link>
            ) : (
              <button
                type="button"
                disabled
                title="Open a file first to convert it"
                className="cursor-not-allowed rounded-sm text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                Convert
              </button>
            )}
          </nav>
          {/* The condensed equivalent below `sm`: a single overflow button revealing the same two
              verbs as menu items, mounted only while open (see the module docstring). */}
          <div className="relative sm:hidden">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={moreOpen}
              aria-controls="toolbar-overflow-menu"
              onClick={() => setMoreOpen((v) => !v)}
              className="inline-flex items-center gap-1 rounded-sm px-1.5 py-1 text-sm text-muted transition-colors hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Menu <span aria-hidden="true">▾</span>
            </button>
            {moreOpen ? (
              <div
                id="toolbar-overflow-menu"
                role="menu"
                aria-label="File actions"
                className="absolute left-0 top-full z-40 mt-1 min-w-40 rounded-md border border-wb-hairline bg-wb-toolbar p-1 shadow-lg"
              >
                <Link
                  href="/"
                  role="menuitem"
                  onClick={() => setMoreOpen(false)}
                  className="block rounded px-2 py-1.5 text-sm text-muted hover:bg-well hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Open / Upload
                </Link>
                {convertHref ? (
                  <Link
                    href={convertHref}
                    role="menuitem"
                    onClick={() => setMoreOpen(false)}
                    className="block rounded px-2 py-1.5 text-sm text-muted hover:bg-well hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    Convert
                  </Link>
                ) : (
                  <span
                    role="menuitem"
                    aria-disabled="true"
                    className="block px-2 py-1.5 text-sm text-faint"
                  >
                    Convert
                  </span>
                )}
              </div>
            ) : null}
          </div>
        </div>

        {/* Right cluster: ⌘K, the global destinations, then the toggles (design spec order). */}
        <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {/* The ⌘K command palette (ported from AppHeader S4): visible button + global ⌘K/Ctrl-K. */}
          <CommandPaletteTrigger />
          <nav aria-label="Primary" className="flex items-center gap-x-4">
            {GLOBAL_DESTINATIONS.map((item) => (
              <Link key={item.href} href={item.href} className={linkClass}>
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <NotifyToggle />
            <ThemeToggle />
          </div>
        </div>
      </div>
    </header>
  );
}
