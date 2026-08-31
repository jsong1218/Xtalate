"use client";

import { useEffect, useRef, useState } from "react";
import { copyText } from "@/lib/report/exportReport";
import {
  FILTERS,
  GROUPING_MODE_LABELS,
  OUTCOME_LABELS,
  type GroupingMode,
  type ReportFilter,
} from "@/lib/report/grouping";

/**
 * The Conversion Report toolbar (UI redesign S3, D245; design spec §5) — grouping toggle, filter
 * chips with live counts, and the export/share controls.
 *
 * - **Grouping:** Outcome (default) vs Category; the choice persists via localStorage (D-R6).
 * - **Filter chips:** `All · Kept · Lost · Assumed · Warned` with live counts; clicking narrows the
 *   visible rows only. The chips are real buttons with `aria-pressed`, so the active filter is
 *   announced, never color-only. Keyboard: `/` focuses the filter from anywhere on the page.
 * - **Export:** Copy as JSON, Copy as Markdown (both pure serializations of the report model — see
 *   `lib/report/exportReport.ts`), and Copy link (the permalink, when the caller knows one). Each
 *   button confirms with a transient "Copied", never a modal.
 */

/** The four chip labels — "All" plus the outcomes in the fixed order. */
const FILTER_LABELS: Record<ReportFilter, string> = {
  all: "All",
  ...OUTCOME_LABELS,
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable
  );
}

export function ReportToolbar({
  mode,
  onModeChange,
  filter,
  onFilterChange,
  counts,
  onCopyJson,
  onCopyMarkdown,
  permalink,
}: {
  mode: GroupingMode;
  onModeChange: (mode: GroupingMode) => void;
  filter: ReportFilter;
  onFilterChange: (filter: ReportFilter) => void;
  /** Live chip counts keyed by filter ("All" carries the full row count). */
  counts: Record<ReportFilter, number>;
  onCopyJson: () => string;
  onCopyMarkdown: () => string;
  /** The durable permalink to this record; when absent the Copy-link control is hidden. */
  permalink?: string;
}) {
  const [copied, setCopied] = useState<"json" | "markdown" | "link" | null>(null);
  const allChipRef = useRef<HTMLButtonElement>(null);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // `/` focuses the filter from anywhere on the page — the design-spec §5 keyboard shortcut.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "/" && !isEditableTarget(event.target)) {
        event.preventDefault();
        allChipRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  async function handleCopy(kind: "json" | "markdown" | "link") {
    const text = kind === "json" ? onCopyJson() : kind === "markdown" ? onCopyMarkdown() : (permalink ?? "");
    if (!text) return;
    const ok = await copyText(text);
    if (!ok) return; // No clipboard available — stay quiet; the serializers still worked.
    if (copiedTimer.current) clearTimeout(copiedTimer.current);
    setCopied(kind);
    copiedTimer.current = setTimeout(() => setCopied(null), 1500);
  }

  const modeButtonClass = (active: boolean) =>
    `rounded-md border px-2.5 py-1 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
      active
        ? "border-accent bg-raised text-accent-text"
        : "border-line bg-surface text-body hover:bg-raised"
    }`;

  const chipClass = (active: boolean) =>
    `inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
      active ? "border-accent bg-raised text-accent-text" : "border-line bg-surface text-body hover:bg-raised"
    }`;

  const exportButtonClass =
    "rounded-md border border-line bg-surface px-2.5 py-1 text-sm text-body transition-colors hover:bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-2"
      aria-label="Report tools"
      onKeyDown={(event) => {
        // Also handle `/` when the toolbar itself is focused (a stray key never types a slash).
        if (event.key === "/" && !isEditableTarget(event.target)) {
          event.preventDefault();
          allChipRef.current?.focus();
        }
      }}
    >
      {/* Grouping toggle — Outcome (default) vs Category, persisted. */}
      <div className="flex items-center gap-1" role="group" aria-label="Group by">
        {(Object.keys(GROUPING_MODE_LABELS) as GroupingMode[]).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => onModeChange(m)}
            className={modeButtonClass(mode === m)}
          >
            {GROUPING_MODE_LABELS[m]}
          </button>
        ))}
      </div>

      {/* Filter chips with live counts — narrowing the visible rows only. */}
      <div className="flex flex-wrap items-center gap-1" data-testid="report-filter-chips">
        {FILTERS.map((f) => {
          const active = filter === f;
          return (
            <button
              key={f}
              type="button"
              ref={f === "all" ? allChipRef : undefined}
              aria-pressed={active}
              data-testid={`report-filter-chip-${f}`}
              onClick={() => onFilterChange(f)}
              className={chipClass(active)}
            >
              {FILTER_LABELS[f]} <span className="font-mono text-xs">{counts[f]}</span>
            </button>
          );
        })}
      </div>

      {/* Export / share. */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" onClick={() => handleCopy("json")} className={exportButtonClass}>
          {copied === "json" ? "Copied" : "Copy as JSON"}
        </button>
        <button type="button" onClick={() => handleCopy("markdown")} className={exportButtonClass}>
          {copied === "markdown" ? "Copied" : "Copy as Markdown"}
        </button>
        {permalink ? (
          <button type="button" onClick={() => handleCopy("link")} className={exportButtonClass}>
            {copied === "link" ? "Copied" : "Copy link"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
