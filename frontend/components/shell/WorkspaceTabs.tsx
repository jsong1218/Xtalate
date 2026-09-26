"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The center tab strip (v2.0 addendums, Task 11; design spec §"Shell architecture" — "The center
 * tab bar reworks the existing `components/shell/WorkspaceTabs.tsx` into the workbench tab strip,
 * rendering real `<Link>`s to `/f/[file_id]/{report,structure,convert,analysis,compare}` (existing
 * routes, unchanged)").
 *
 * Two corrections against that literal route list, made the same way Task 8's `Toolbar` already
 * corrected its own verb set against what actually exists (its "Deliberately NOT included" note):
 *
 *  - **No `compare` route exists** under `app/f/[file_id]/` (only `analysis`, `convert`, `report`,
 *    `structure`, and the bare overview page do) — a Compare tab would be a dead link, so it is
 *    omitted. `CompareTab.tsx` is rendered *inside* the Report route's own conversion record, not at
 *    a standalone `/f/[file_id]/compare` URL.
 *  - **`report` is not a bare route either** — only `/f/[file_id]/report/[conversion_id]` exists,
 *    because a report is a specific conversion's, not the file's. There is no report URL to jump to
 *    except while already viewing one, so — preserving the pre-Task-11 behavior — the Report tab
 *    links only on a report route and otherwise renders as an inert, disabled tab rather than a
 *    link that would 404; the convert flow surfaces the real report link in-content once one exists.
 *
 * Design intent orders **Report first**, then Structure, Convert, Analysis — the report is the
 * product's payoff (what was kept/lost/assumed), so it leads even though it is usually inert until a
 * conversion exists. The bare overview tab (`/f/[file_id]`, labeled "Inspect") predates this design
 * pass and isn't named in it; Task 10 already absorbed its filename/format/field-count content into
 * the persistent Inspector rail (shown on every `/f/[file_id]/*` route), so it is kept — dropping a
 * working route would be a silent regression — but appended after the four named tabs rather than
 * displacing Report from the lead position the design calls for.
 *
 * The active tab wears the accent-text token (the S1 `--accent-text` role) with an
 * `aria-current="page"` link, never a hard-coded hue.
 */
const ROUTED_TABS = [
  { key: "structure", label: "Structure" },
  { key: "convert", label: "Convert" },
  { key: "analysis", label: "Analysis" },
] as const;

export function WorkspaceTabs({ fileId }: { fileId: string }) {
  const pathname = usePathname();
  const base = `/f/${fileId}`;

  const hrefFor = (key: (typeof ROUTED_TABS)[number]["key"]): string => `${base}/${key}`;
  const activeFor = (key: (typeof ROUTED_TABS)[number]["key"]): boolean =>
    pathname === hrefFor(key);

  const onReportRoute = pathname.startsWith(`${base}/report/`);
  const onOverviewRoute = pathname === base;

  const linkClass = (active: boolean) =>
    `-mb-px border-b-2 px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
      active
        ? "border-accent text-accent-text"
        : "border-transparent text-muted hover:text-accent-text"
    }`;

  return (
    <nav aria-label="Workspace" className="flex flex-wrap gap-1 border-b border-line">
      {onReportRoute ? (
        <Link href={pathname} aria-current="page" className={linkClass(true)}>
          Report
        </Link>
      ) : (
        <span
          aria-disabled="true"
          title="No conversion report yet — the convert tab links to a report once one exists."
          className="-mb-px cursor-default border-b-2 border-transparent px-3 py-2 text-sm text-faint"
        >
          Report
        </span>
      )}
      {ROUTED_TABS.map((tab) => {
        const active = activeFor(tab.key);
        return (
          <Link
            key={tab.key}
            href={hrefFor(tab.key)}
            aria-current={active ? "page" : undefined}
            className={linkClass(active)}
          >
            {tab.label}
          </Link>
        );
      })}
      <Link
        href={base}
        aria-current={onOverviewRoute ? "page" : undefined}
        className={linkClass(onOverviewRoute)}
      >
        Inspect
      </Link>
    </nav>
  );
}
