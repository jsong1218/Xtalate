/**
 * Pure grouping logic for the S4 collapsible report groups (frontend redesign addendum §4.4).
 *
 * The report panels can flood at trajectory scale — dozens of same-code warnings, a long Removed
 * list. Grouping same-typed entries into one expanded-by-default disclosure cuts the wall of text
 * *without* burying anything (the disclosures start open — nothing needs a click to become visible),
 * complementing the engine-side D108 per-frame frame-range collapse.
 *
 * This module owns only the arithmetic — which entries share a key, in what order, and whether the
 * repetition is worth grouping at all. The panel owns the rendering. Keeping it here makes the two
 * guarantees below unit-testable in isolation.
 */

export interface Group<T> {
  /** The shared key (a warning `code`, a canonical category); used as the group's heading + React key. */
  key: string;
  items: T[];
}

/**
 * Bucket `items` by `keyOf`, with groups in **first-seen key order** and each group's items in the
 * order they were encountered. Order is load-bearing: the rendered groups must track the report
 * arrays, never a re-sorted view that would reorder what the engine reported.
 */
export function groupByKey<T>(items: readonly T[], keyOf: (item: T) => string): Group<T>[] {
  const byKey = new Map<string, Group<T>>();
  const order: Group<T>[] = [];
  for (const item of items) {
    const key = keyOf(item);
    let group = byKey.get(key);
    if (group === undefined) {
      group = { key, items: [] };
      byKey.set(key, group);
      order.push(group);
    }
    group.items.push(item);
  }
  return order;
}

/**
 * Whether a section should render as collapsible groups rather than a flat list. True **only when a
 * key repeats** (some group holds ≥ 2 items) — that is the flood grouping exists to tame. A section
 * whose entries are all distinct stays flat, so a single warning is never dressed up as an accordion
 * of one.
 */
export function shouldCollapse<T>(groups: readonly Group<T>[]): boolean {
  return groups.some((group) => group.items.length >= 2);
}

// --- Outcome-first report grouping (UI redesign S3, D245) ---------------------------------------
//
// The report's two orthogonal views: **outcome-first** (Assumed → Lost → Warned → Kept, the S3
// default) and **canonical-category** (Atoms / Cell / Dynamics / … across outcomes). This module
// owns the pure structure — which outcome/category each row belongs to, in what order, and the
// persisted choice — while the panel owns rendering. The ordering rules are load-bearing:
// outcome order is fixed by OUTCOME_ORDER, category order is **first-seen across the report's own
// array order**, and nothing is ever dropped from the view model — the no-loss invariant is
// asserted on this module (a row exists for every preserved/removed/assumption/warning entry).

import type {
  Assumption,
  ConversionReport,
  PreservedEntry,
  RemovedEntry,
  ReportWarning,
  SuppliedEntry,
} from "./types";

/** The four outcome buckets, in the S3 default render order. */
export type Outcome = "kept" | "lost" | "assumed" | "warned";

/** Outcome-first section order: the losses and fabrications lead, the kept follows. */
export const OUTCOME_ORDER: readonly Outcome[] = ["assumed", "lost", "warned", "kept"];

/** Plain-language section titles, e.g. the "Assumed (2)" heading. */
export const OUTCOME_LABELS: Record<Outcome, string> = {
  assumed: "Assumed",
  lost: "Lost",
  warned: "Warned",
  kept: "Kept",
};

/** The row kinds the Conversion Report panel renders, and the outcome each belongs to. */
export type ReportRowKind = "preserved" | "removed" | "assumed" | "warned";

/** The outcome a report row belongs to — kept/lost/assumed/warned (Part 4 §2 arrays). */
export function outcomeOf(kind: ReportRowKind): Outcome {
  switch (kind) {
    case "preserved":
      return "kept";
    case "removed":
      return "lost";
    case "assumed":
      return "assumed";
    case "warned":
      return "warned";
  }
}

/**
 * The top-level canonical category a field path belongs to, e.g. `dynamics.forces` → `dynamics`
 * (Part 2 §3). The same concept the S4 Removed-body collapses on; exported here so both the panel
 * and the grouping logic share one definition.
 */
export function canonicalCategory(path: string): string {
  const dot = path.indexOf(".");
  return dot === -1 ? path : path.slice(0, dot);
}

/** A canonical category token as a plain heading, e.g. `user_metadata` → "User metadata". */
export function categoryLabel(category: string): string {
  const words = category.split("_");
  const [first, ...rest] = words;
  const head = first.charAt(0).toUpperCase() + first.slice(1);
  return [head, ...rest].join(" ");
}

/**
 * One normalized row of the report — the unit the outcome/category views are built from. `entry`
 * carries the report-model element itself, so the panel renders without a lookup (and row
 * completeness is checkable here: one row per model entry, never fewer). Warnings are one row per
 * warning (duplicate codes are distinct rows); supplied fields ride inside their assumption's row
 * rather than as separate rows — the panel renders them there, so the view model matches what is
 * rendered.
 */
export interface ReportRow {
  /** Stable unique key for React. */
  id: string;
  kind: ReportRowKind;
  outcome: Outcome;
  /** The canonical category token (a top-level path, or the `warnings`/`recovery` pseudo-categories
   *  for rows that have no canonical field of their own). */
  category: string;
  /** The canonical path for field rows; `null` for warnings and pathless assumptions. */
  path: string | null;
  entry: PreservedEntry | RemovedEntry | Assumption | ReportWarning | SuppliedEntry;
}

/** Category tokens for rows the report does not attach a canonical path to (warnings, pathless
 *  assumptions) — they are still rows and still render, so they get honest buckets of their own. */
export const PATHLESS_CATEGORY = {
  warnings: "warnings",
  recovery: "recovery",
} as const;

/**
 * Flatten a report into one {@link ReportRow} per preserved / removed / assumption / warning entry,
 * in the report's own array order. The no-loss invariant lives here: every entry of those four
 * arrays appears exactly once. (Supplied entries are not separate rows — the panel renders them
 * inside their assumption's row, the Part 4 §2 one-to-many join, with the orphan-proof rendering.)
 */
export function buildReportRows(report: ConversionReport): ReportRow[] {
  const rows: ReportRow[] = [];
  for (const entry of report.preserved) {
    rows.push({
      id: `preserved-${entry.path}`,
      kind: "preserved",
      outcome: "kept",
      category: canonicalCategory(entry.path),
      path: entry.path,
      entry,
    });
  }
  for (const entry of report.removed) {
    rows.push({
      id: `removed-${entry.path}`,
      kind: "removed",
      outcome: "lost",
      category: canonicalCategory(entry.path),
      path: entry.path,
      entry,
    });
  }
  for (const entry of report.assumptions) {
    // An assumption's category is the canonical category of the field it supplied, when it
    // supplied one — otherwise the recovery bucket (a decision with no field of its own).
    const suppliedPath = report.supplied.find((s) => s.from_assumption === entry.id)?.path;
    rows.push({
      id: `assumed-${entry.id}`,
      kind: "assumed",
      outcome: "assumed",
      category: suppliedPath ? canonicalCategory(suppliedPath) : PATHLESS_CATEGORY.recovery,
      path: null,
      entry,
    });
  }
  report.warnings.forEach((entry, i) => {
    rows.push({
      id: `warned-${entry.code}-${i}`,
      kind: "warned",
      outcome: "warned",
      category: PATHLESS_CATEGORY.warnings,
      path: null,
      entry,
    });
  });
  // Orphaned supplied entries — a `from_assumption` that matches no assumption in this report (an
  // engine bug, a hand-edited fixture) — are still rendered by the panel as an assumption row, so
  // the view model carries them too: row completeness means *every rendered row has a model row*.
  const assumptionIds = new Set(report.assumptions.map((a) => a.id));
  for (const entry of report.supplied) {
    if (assumptionIds.has(entry.from_assumption)) continue;
    rows.push({
      id: `assumed-orphaned-${entry.path}`,
      kind: "assumed",
      outcome: "assumed",
      category: canonicalCategory(entry.path),
      path: entry.path,
      entry,
    });
  }
  return rows;
}

/** A group of rows with a stable key + plain heading — one section in the rendered report. */
export interface RowSection {
  key: string;
  label: string;
  rows: ReportRow[];
}

/** Bucket rows by outcome, in the fixed {@link OUTCOME_ORDER}, dropping empty buckets. */
export function groupRowsByOutcome(rows: readonly ReportRow[]): RowSection[] {
  const byOutcome = new Map<Outcome, ReportRow[]>();
  for (const row of rows) {
    const list = byOutcome.get(row.outcome) ?? [];
    list.push(row);
    byOutcome.set(row.outcome, list);
  }
  const sections: RowSection[] = [];
  for (const outcome of OUTCOME_ORDER) {
    const group = byOutcome.get(outcome);
    if (group && group.length > 0) {
      sections.push({ key: outcome, label: OUTCOME_LABELS[outcome], rows: group });
    }
  }
  return sections;
}

/** Bucket rows by canonical category, in **first-seen** order across the row list (the report's own
 *  array order), dropping empty buckets. First-seen keeps the order stable and free of an
 *  opinionated sort — the rendered categories track the report, never a re-sorted view. */
export function groupRowsByCategory(rows: readonly ReportRow[]): RowSection[] {
  const byCategory = new Map<string, ReportRow[]>();
  const order: string[] = [];
  for (const row of rows) {
    const list = byCategory.get(row.category);
    if (list === undefined) {
      byCategory.set(row.category, [row]);
      order.push(row.category);
    } else {
      list.push(row);
    }
  }
  return order.map((category) => ({
    key: category,
    label: categoryLabel(category),
    rows: byCategory.get(category) ?? [],
  }));
}

/** The filter chips' state: `all` or one outcome. */
export type ReportFilter = "all" | Outcome;

/** Filter chips with the four outcomes — in the fixed OUTCOME_ORDER, so the chips never reorder. */
export const FILTERS: readonly ReportFilter[] = ["all", "assumed", "lost", "warned", "kept"];

/** Narrow a row list to one outcome (or keep everything). */
export function filterRows(rows: readonly ReportRow[], filter: ReportFilter): ReportRow[] {
  if (filter === "all") return [...rows];
  return rows.filter((row) => row.outcome === filter);
}

/** Counts per filter — live chip labels: All (n) · Kept (n) · … */
export function countByFilter(rows: readonly ReportRow[]): Record<ReportFilter, number> {
  const counts: Record<ReportFilter, number> = { all: rows.length, assumed: 0, lost: 0, warned: 0, kept: 0 };
  for (const row of rows) counts[row.outcome] += 1;
  return counts;
}

// --- Persisted grouping choice (D-R6: QoL persistence is client-side) ---------------------------

/** The two grouping modes of the report. */
export type GroupingMode = "outcome" | "category";

/** Plain labels for the grouping toggle. */
export const GROUPING_MODE_LABELS: Record<GroupingMode, string> = {
  outcome: "Outcome",
  category: "Category",
};

/** localStorage key (the `xtalate-` prefix convention; see the theme/notify providers). */
export const REPORT_GROUPING_STORAGE_KEY = "xtalate-report-grouping";

/** The S3 default: outcome-first. */
export const DEFAULT_GROUPING_MODE: GroupingMode = "outcome";

function isGroupingMode(value: string | null): value is GroupingMode {
  return value === "outcome" || value === "category";
}

/** Read the persisted grouping mode; falls back to the default when unset or unavailable (SSR,
 *  privacy mode — localStorage can throw, same guard the theme provider uses). */
export function loadGroupingMode(): GroupingMode {
  if (typeof window === "undefined") return DEFAULT_GROUPING_MODE;
  try {
    const value = window.localStorage.getItem(REPORT_GROUPING_STORAGE_KEY);
    return isGroupingMode(value) ? value : DEFAULT_GROUPING_MODE;
  } catch {
    return DEFAULT_GROUPING_MODE;
  }
}

/** Persist the grouping choice (best-effort; a storage failure never breaks rendering). */
export function saveGroupingMode(mode: GroupingMode): void {
  try {
    window.localStorage.setItem(REPORT_GROUPING_STORAGE_KEY, mode);
  } catch {
    // No persistence available (privacy mode, SSR) — the choice just doesn't survive a reload.
  }
}
