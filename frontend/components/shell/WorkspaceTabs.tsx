"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The workspace tab bar (UI redesign S2, D244; design spec §3, D-R1/D-R5).
 *
 * `Inspect · Structure · Convert · Report` are the real surfaces (plus Analysis, the S6 empty seam),
 * and every tab is a route — so tabs are always clickable and a power user jumps straight to
 * Convert. The active tab wears the accent-text token (the S1 `--accent-text` role) with an
 * `aria-current="page"` link, never a hard-coded hue.
 *
 * The Report tab is the one tab that needs a conversion id in its URL (`/f/[id]/report/[cid]`).
 * While the workspace is on that route it links to the report in view; from any other tab there is
 * no report URL to jump to, so it renders as an inert, disabled tab rather than a link that would
 * 404 — the convert flow surfaces the real report link in-content when one exists.
 */
const TABS = [
  { key: "inspect", label: "Inspect" },
  { key: "structure", label: "Structure" },
  { key: "convert", label: "Convert" },
  { key: "analysis", label: "Analysis" },
] as const;

export function WorkspaceTabs({ fileId }: { fileId: string }) {
  const pathname = usePathname();
  const base = `/f/${fileId}`;

  const hrefFor = (key: (typeof TABS)[number]["key"]): string =>
    key === "inspect" ? base : `${base}/${key}`;
  const activeFor = (key: (typeof TABS)[number]["key"]): boolean =>
    pathname === hrefFor(key);

  const onReportRoute = pathname.startsWith(`${base}/report/`);

  const linkClass = (active: boolean) =>
    `-mb-px border-b-2 px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
      active
        ? "border-accent text-accent-text"
        : "border-transparent text-muted hover:text-accent-text"
    }`;

  return (
    <nav aria-label="Workspace" className="flex flex-wrap gap-1 border-b border-line">
      {TABS.map((tab) => {
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
    </nav>
  );
}
