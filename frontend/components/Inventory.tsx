import { LossIcon, type LossKind } from "@/components/loss/icons";
import { Row } from "@/components/report/Row";
import { labelForPath } from "@/lib/mapping";
import type { DiscoveryReport, FieldPresenceEntry } from "@/lib/report/types";

/**
 * The contents inventory — the "✓ Species / ✗ Lattice" answer to *what is in this file* (MASTER_SPEC
 * Part 3 §6, Part 7 §4; slice M28-S2). It renders the Discovery Report's fixed leaf-path inventory,
 * one row per canonical field, in the report's own order — so a reader with the JSON open can match
 * every row and "not shown" can never be mistaken for "not checked" (§6.3).
 *
 * The load-bearing distinction this component exists to draw is between two kinds of *absence*
 * (Part 7 §4): a field the source lacks but the **format could express** (`○`, absent-file — "your
 * file could have carried this") versus one the **format cannot express at all** (`✗`, muted,
 * absent-format — a calm fact about the format, not a loss). Collapsing them would tell a user their
 * file is missing something when the format was never going to hold it. Presence is `✓`.
 *
 * Parse warnings render in an amber band **above** the inventory: an output that only parsed *with*
 * warnings is itself a finding, and it must be read before the inventory it qualifies — so the band
 * is structurally first, not tucked below.
 */

/** Map one presence entry to its §4 loss kind — the three-way ✓ / ○ / ✗-muted decision. */
export function inventoryKind(entry: FieldPresenceEntry): LossKind {
  if (entry.status === "present" || entry.status === "mixed") return "preserved";
  // Absent: the format's read-side capability decides which absence this is.
  return entry.format_capability === "none" ? "absent-format" : "absent-file";
}

/** Detail line for a row — a mixed field names the frames it is present in; else the engine detail. */
function inventoryDetail(entry: FieldPresenceEntry): string | null {
  if (entry.status === "mixed" && entry.present_frames) {
    return `Present in frames ${JSON.stringify(entry.present_frames)}`;
  }
  return entry.detail;
}

function ParseWarningsBand({ report }: { report: DiscoveryReport }) {
  if (report.issues.length === 0) return null;
  return (
    <section
      aria-label="Parse warnings"
      className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3"
    >
      <h3 className="flex items-center gap-2 text-sm font-semibold text-amber-900">
        <LossIcon kind="warning" />
        {report.issues.length === 1
          ? "This file parsed with 1 warning"
          : `This file parsed with ${report.issues.length} warnings`}
      </h3>
      <ul className="mt-2 space-y-2">
        {report.issues.map((issue, i) => (
          <li key={`${issue.code}-${i}`} className="text-sm text-amber-900">
            <code className="rounded bg-amber-100 px-1 py-0.5 font-mono text-xs text-amber-900">
              {issue.code}
            </code>{" "}
            <span>{issue.message}</span>
            {issue.location ? (
              <span className="text-amber-700"> ({issue.location})</span>
            ) : null}
            {issue.recovery_hint ? (
              <div className="mt-0.5 text-amber-700">{issue.recovery_hint}</div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Inventory({ report }: { report: DiscoveryReport }) {
  return (
    <div className="space-y-4">
      <ParseWarningsBand report={report} />
      <section aria-label="Contents inventory" className="rounded-md border border-slate-200">
        <h3 className="border-b border-slate-200 px-3 py-2 text-sm font-semibold text-slate-900">
          What this file contains
        </h3>
        <ul className="divide-y divide-slate-100">
          {report.fields.map((entry) => (
            <Row
              key={entry.path}
              kind={inventoryKind(entry)}
              label={labelForPath(entry.path).label}
              detail={inventoryDetail(entry)}
              testId={`inventory-${entry.path}`}
            />
          ))}
        </ul>
      </section>
    </div>
  );
}
