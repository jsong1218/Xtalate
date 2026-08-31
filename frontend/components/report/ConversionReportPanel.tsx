import { useMemo, useRef, useState, type ReactNode } from "react";
import { labelForPath, labelForScenario } from "@/lib/mapping";
import {
  buildReportRows,
  canonicalCategory,
  categoryLabel,
  countByFilter,
  filterRows,
  groupByKey,
  groupRowsByCategory,
  loadGroupingMode,
  OUTCOME_ORDER,
  OUTCOME_LABELS,
  saveGroupingMode,
  shouldCollapse,
  type GroupingMode,
  type ReportFilter,
  type ReportRow,
} from "@/lib/report/grouping";
import { reportToJson, reportToMarkdown } from "@/lib/report/exportReport";
import type {
  Assumption,
  ConversionReport,
  PreservedEntry,
  RemovedEntry,
  ReportWarning,
  SuppliedEntry,
} from "@/lib/report/types";
import { Row } from "./Row";
import { ReportToolbar } from "./ReportToolbar";
import { SummaryChips } from "./SummaryChips";

/**
 * The Conversion Report panel — the design-critical surface (MASTER_SPEC Part 7 §4.3, redesigned
 * outcome-first by UI redesign S3, D245; design spec §5).
 *
 * **Outcome-first by default (Assumed → Lost → Warned → Kept).** The old section order followed the
 * schema (Preserved first); the S3 order leads with what a reader must see — what was fabricated,
 * what was lost, what was warned — and ends with what was kept. A toggle switches to canonical
 * **category** grouping (Atoms / Cell / Dynamics / … across outcomes), and the choice persists
 * (localStorage, D-R6).
 *
 * **Filter chips** narrow the visible rows only (`All · Kept · Lost · Assumed · Warned`, live
 * counts, `aria-pressed`); `/` focuses the filter. **Rows** show the source value in mono
 * (never collapsed away) and the outcome tag; assumptions state what was supplied and that it was
 * recorded as an assumption, verbatim from the report (P4). **Export** is Copy-as-JSON /
 * Copy-as-Markdown (pure serializations of the report model) plus Copy-link to the permalink.
 *
 * Invariants that survive the redesign (and are asserted by the no-loss invariant test):
 *  - **Row completeness.** Every section is a `report.<array>.map(...)` (or a view-model row per
 *    entry) with no filtering, no truncation, no reordering of the report arrays; the S4
 *    same-type disclosures re-parent rows but never remove one.
 *  - **Reason verbatim.** A Removed row shows its `reason` exactly as the engine wrote it.
 *  - **Supplied + Assumptions adjacent, in the shared ◆ violet** — fabricated data is \"a third
 *    thing\", never demoted below the losses it sits beside.
 *  - **Plain language, code one step away** — paths/scenarios resolve through `lib/mapping.ts`.
 *  - **Empty sections are omitted, but the always-present {@link SummaryChips} carry the
 *    affirmative zero accounting** (\"✓ 0 fields removed\"), so omission is never a silent blank.
 *
 * The redesign changes **which sections appear and in what order — never which rows or what they
 * say** (design spec §5 invariant). A refusal still renders as a completed, honest report (status
 * `refused`), not an error — the refusal content renders through the record page, not here.
 */

/** The left accent bar per outcome section, bound to the `--cb-*` loss palette. */
const OUTCOME_TINT: Record<(typeof OUTCOME_ORDER)[number], string> = {
  assumed: "border-cb-assumption",
  lost: "border-cb-removed",
  warned: "border-cb-warning",
  kept: "border-cb-preserve",
};

function Section({
  title,
  count,
  tint,
  testId,
  wrapList = true,
  children,
}: {
  title: string;
  count: number;
  /** Left accent bar color class, bound to a `--cb-*` token. */
  tint: string;
  /** Stable hook for the invariant test + the e2e journey (section order, counts). */
  testId?: string;
  /** When true (default) the section wraps its rows in a divided `<ul>`; grouped sections manage
   *  their own list/disclosure structure and pass false. */
  wrapList?: boolean;
  children: ReactNode;
}) {
  if (count === 0) return null;
  const headingId = `report-section-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section
      aria-labelledby={headingId}
      data-testid={testId}
      className={`border-l-2 pl-3 ${tint}`}
    >
      <h3 id={headingId} className="mb-1 text-sm font-semibold text-body">
        {title} <span className="font-normal text-faint">({count})</span>
      </h3>
      {wrapList ? <ul className="divide-y divide-line-soft">{children}</ul> : children}
    </section>
  );
}

/**
 * An expanded-by-default disclosure holding same-typed rows (addendum S4). It starts `open` — the
 * grouping tames the wall of text without hiding a single row behind a required click — and its rows
 * live in the same divided `<ul>` a flat section uses, so row-completeness assertions are unaffected.
 */
function CollapsibleGroup({
  heading,
  count,
  children,
}: {
  heading: ReactNode;
  count: number;
  children: ReactNode;
}) {
  return (
    <details open data-testid="report-group" className="rounded-md border border-line-soft bg-raised">
      <summary className="flex cursor-pointer select-none flex-wrap items-center gap-2 px-3 py-2 text-sm font-medium text-body">
        {heading}
        <span className="font-normal text-faint">({count})</span>
      </summary>
      <ul className="divide-y divide-line-soft border-t border-line-soft">{children}</ul>
    </details>
  );
}

/** A Removed row: field name, the engine's `reason` verbatim, then the quantitative loss in mono. */
function RemovedRow({ entry }: { entry: RemovedEntry }) {
  return (
    <Row
      kind="removed"
      testId="removed-row"
      label={labelForPath(entry.path).label}
      detail={entry.detail}
    >
      <p className="text-sm text-body">{entry.reason}</p>
    </Row>
  );
}

/**
 * The Removed section body — flat when the losses are all distinct categories, grouped by canonical
 * category once a category repeats (a lengthy `dynamics.*`/`electronic.*` list collapses into
 * one open disclosure per category rather than a long undivided run).
 */
function RemovedBody({ removed }: { removed: RemovedEntry[] }) {
  const groups = groupByKey(removed, (entry) => canonicalCategory(entry.path));
  if (!shouldCollapse(groups)) {
    return (
      <ul className="divide-y divide-line-soft">
        {removed.map((entry, i) => (
          <RemovedRow key={`${entry.path}-${i}`} entry={entry} />
        ))}
      </ul>
    );
  }
  return (
    <div className="space-y-2">
      {groups.map((group) => (
        <CollapsibleGroup
          key={group.key}
          count={group.items.length}
          heading={<span className="text-strong">{categoryLabel(group.key)}</span>}
        >
          {group.items.map((entry, i) => (
            <RemovedRow key={`${group.key}-${entry.path}-${i}`} entry={entry} />
          ))}
        </CollapsibleGroup>
      ))}
    </div>
  );
}

/** The stable warning `code` badge; its `source` rides in the tooltip, as on the flat row. */
function WarningCode({ code, source }: { code: string; source: string }) {
  return (
    <code
      className="rounded bg-cb-warning-bg px-1.5 py-0.5 text-xs text-cb-warning"
      title={`source: ${source}`}
    >
      {code}
    </code>
  );
}

/** One warning row. In a group the `code` heads the disclosure, so the row carries the message alone. */
function WarningRow({ warning, showCode }: { warning: ReportWarning; showCode: boolean }) {
  return (
    <Row
      kind="warning"
      testId="warning-row"
      label={
        showCode ? (
          <span className="flex flex-wrap items-center gap-2">
            <WarningCode code={warning.code} source={warning.source} />
            <span className="font-normal text-strong">{warning.message}</span>
          </span>
        ) : (
          <span className="font-normal text-strong">{warning.message}</span>
        )
      }
    />
  );
}

/**
 * The Warnings section body — flat when every warning is a distinct code, grouped by `code` once a
 * code repeats. The repeated-code case is the trajectory flood (many frames raising the same note);
 * grouping shows the code + count once and keeps every verbatim message a row inside the open group.
 */
function WarningsBody({ warnings }: { warnings: ReportWarning[] }) {
  const groups = groupByKey(warnings, (warning) => warning.code);
  if (!shouldCollapse(groups)) {
    return (
      <ul className="divide-y divide-line-soft">
        {warnings.map((warning, i) => (
          <WarningRow key={`${warning.code}-${i}`} warning={warning} showCode />
        ))}
      </ul>
    );
  }
  return (
    <div className="space-y-2">
      {groups.map((group) => (
        <CollapsibleGroup
          key={group.key}
          count={group.items.length}
          heading={<WarningCode code={group.key} source={group.items[0].source} />}
        >
          {group.items.map((warning, i) => (
            <WarningRow key={`${group.key}-${i}`} warning={warning} showCode={false} />
          ))}
        </CollapsibleGroup>
      ))}
    </div>
  );
}

/** An Assumption and the Supplied fields it authorized, rendered together (the ◆ "third thing"). */
function AssumptionRow({
  assumption,
  supplied,
}: {
  assumption: Assumption;
  supplied: SuppliedEntry[];
}) {
  const scenario = labelForScenario(assumption.scenario);
  return (
    <Row
      kind="assumption"
      testId="assumption-row"
      // The stable fragment anchor the Structure tab's supplied-geometry link lands on — the
      // Assumption one click away from the violet cell (v1.6 M60-S3, D235).
      id={`assumption-${assumption.id}`}
      label={
        <span>
          {scenario.label}{" "}
          <code className="rounded bg-cb-assumption-bg px-1 py-0.5 text-xs text-cb-assumption">
            {assumption.choice}
          </code>
        </span>
      }
      detail={assumption.description}
    >
      {supplied.length > 0 ? (
        <ul className="mt-1 space-y-0.5">
          {supplied.map((entry) => (
            <li key={entry.path} data-testid="supplied-row" className="text-sm text-muted">
              <span className="text-cb-assumption">+ </span>
              {labelForPath(entry.path).label}
              {entry.detail ? <span className="text-faint"> — {entry.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </Row>
  );
}

/**
 * The Assumed section body — every assumption plus the Supplied fields it authorized, with the
 * orphan-proof join (a supplied entry whose `from_assumption` matches nothing must still render).
 * This is the S3 outcome-first home of what the schema calls "Supplied & assumptions".
 */
function AssumptionsBody({ report }: { report: ConversionReport }) {
  const suppliedByAssumption = new Map<string, SuppliedEntry[]>();
  for (const entry of report.supplied) {
    const list = suppliedByAssumption.get(entry.from_assumption) ?? [];
    list.push(entry);
    suppliedByAssumption.set(entry.from_assumption, list);
  }

  const assumptionIds = new Set(report.assumptions.map((a) => a.id));
  const orphanedSupplied = report.supplied.filter((e) => !assumptionIds.has(e.from_assumption));

  return (
    <>
      {report.assumptions.map((assumption) => (
        <AssumptionRow
          key={assumption.id}
          assumption={assumption}
          supplied={suppliedByAssumption.get(assumption.id) ?? []}
        />
      ))}
      {orphanedSupplied.length > 0 ? (
        <Row
          kind="assumption"
          testId="assumption-row"
          label="Supplied fields"
          detail="Recorded without a matching assumption entry in this report."
        >
          <ul className="mt-1 space-y-0.5">
            {orphanedSupplied.map((entry) => (
              <li key={entry.path} data-testid="supplied-row" className="text-sm text-muted">
                <span className="text-cb-assumption">+ </span>
                {labelForPath(entry.path).label}
                {entry.detail ? <span className="text-faint"> — {entry.detail}</span> : null}
              </li>
            ))}
          </ul>
        </Row>
      ) : null}
    </>
  );
}

/** The Kept section body — one preserved row per entry. */
function PreservedBody({ preserved }: { preserved: PreservedEntry[] }) {
  return (
    <>
      {preserved.map((entry) => (
        <Row
          key={entry.path}
          kind="preserved"
          testId="preserved-row"
          label={labelForPath(entry.path).label}
          detail={entry.detail}
        />
      ))}
    </>
  );
}

/** One row in a category section — dispatched by kind to the same renderers the outcome view uses. */
function CategoryRow({ row, report }: { row: ReportRow; report: ConversionReport }) {
  switch (row.kind) {
    case "preserved": {
      const entry = row.entry as PreservedEntry;
      return (
        <Row
          kind="preserved"
          testId="preserved-row"
          label={labelForPath(entry.path).label}
          detail={entry.detail}
        />
      );
    }
    case "removed":
      return <RemovedRow entry={row.entry as RemovedEntry} />;
    case "assumed": {
      const entry = row.entry as Assumption;
      return (
        <AssumptionRow
          assumption={entry}
          supplied={report.supplied.filter((s) => s.from_assumption === entry.id)}
        />
      );
    }
    case "warned":
      return <WarningRow warning={row.entry as ReportWarning} showCode />;
  }
}

export function ConversionReportPanel({
  report,
  permalink,
}: {
  report: ConversionReport;
  /** The durable permalink for Copy-link; absent on surfaces without one (the live job view). */
  permalink?: string;
}) {
  const [mode, setMode] = useState<GroupingMode>(() => loadGroupingMode());
  const [filter, setFilter] = useState<ReportFilter>("all");
  const contentRef = useRef<HTMLDivElement>(null);

  // The normalized view model — one row per model entry (the no-loss invariant's home).
  const rows = useMemo(() => buildReportRows(report), [report]);
  const counts = useMemo(() => countByFilter(rows), [rows]);

  // Report-row keyboard nav (S4, design spec §6): `j` / `k` move focus between rows when focus is
  // already inside the panel (the same vocabulary as the / filter shortcut). Rows are reachable but
  // not in the Tab order (Row.tsx renders tabIndex -1 + data-report-row).
  function onRowNav(e: React.KeyboardEvent) {
    if (e.key !== "j" && e.key !== "k") return;
    if (!contentRef.current) return;
    const rowsEl = Array.from(contentRef.current.querySelectorAll<HTMLElement>("[data-report-row]"));
    if (rowsEl.length === 0) return;
    e.preventDefault();
    const current = document.activeElement as HTMLElement | null;
    const idx = current && rowsEl.includes(current) ? rowsEl.indexOf(current) : -1;
    const next = e.key === "j" ? (idx + 1) % rowsEl.length : (idx - 1 + rowsEl.length) % rowsEl.length;
    if (e.key === "j" && idx === -1) {
      // No active row yet: j drops onto the first row.
      rowsEl[0].focus();
    } else {
      rowsEl[next].focus();
    }
  }

  function changeMode(next: GroupingMode) {
    setMode(next);
    saveGroupingMode(next);
  }

  const source = report.source;
  const target = report.target;

  return (
    <div
      ref={contentRef}
      onKeyDown={onRowNav}
      className="space-y-4 rounded-lg border border-line p-4 focus-within:ring-1 focus-within:ring-accent"
    >
      <header className="space-y-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-strong">Conversion report</h2>
          <p className="text-sm text-muted">
            <span className="font-medium text-strong">{source.filename}</span>{" "}
            <span className="text-faint">({source.format_id})</span>
            <span aria-hidden="true"> → </span>
            <span className="font-medium text-strong">{target.filename}</span>{" "}
            <span className="text-faint">({target.format_id})</span>
            <span className="ml-2 rounded bg-well px-1.5 py-0.5 text-xs text-muted">
              {report.mode}
            </span>
          </p>
        </div>
        {/* The summary band: the count chips elevated to a distinct at-a-glance overview (S4). */}
        <div
          data-testid="report-summary-band"
          className="rounded-md border border-line bg-well px-3 py-2.5"
        >
          <SummaryChips report={report} />
        </div>
        {/* The S3 toolbar: grouping toggle, filter chips, export/share. */}
        <ReportToolbar
          mode={mode}
          onModeChange={changeMode}
          filter={filter}
          onFilterChange={setFilter}
          counts={counts}
          onCopyJson={() => reportToJson(report)}
          onCopyMarkdown={() => reportToMarkdown(report)}
          permalink={permalink}
        />
      </header>

      {mode === "outcome" ? (
        <OutcomeSections report={report} filter={filter} counts={counts} />
      ) : (
        <CategorySections report={report} rows={rows} filter={filter} />
      )}
    </div>
  );
}

/**
 * The outcome-first view (S3 default): sections in OUTCOME_ORDER, each rendering its rows through
 * the shared bodies (S4 same-type disclosures included). A non-`all` filter shows only the matching
 * section — narrowing the visible rows, never touching the model.
 */
function OutcomeSections({
  report,
  filter,
  counts,
}: {
  report: ConversionReport;
  filter: ReportFilter;
  counts: Record<ReportFilter, number>;
}) {
  const sectionVisible = (outcome: (typeof OUTCOME_ORDER)[number]) =>
    filter === "all" || filter === outcome;

  return (
    <div className="space-y-4">
      {sectionVisible("assumed") ? (
        <Section
          title={OUTCOME_LABELS.assumed}
          count={counts.assumed}
          tint={OUTCOME_TINT.assumed}
          testId="report-section-assumed"
        >
          <AssumptionsBody report={report} />
        </Section>
      ) : null}

      {sectionVisible("lost") ? (
        <Section
          title={OUTCOME_LABELS.lost}
          count={report.removed.length}
          tint={OUTCOME_TINT.lost}
          testId="report-section-lost"
          wrapList={false}
        >
          <RemovedBody removed={report.removed} />
        </Section>
      ) : null}

      {sectionVisible("warned") ? (
        <Section
          title={OUTCOME_LABELS.warned}
          count={report.warnings.length}
          tint={OUTCOME_TINT.warned}
          testId="report-section-warned"
          wrapList={false}
        >
          <WarningsBody warnings={report.warnings} />
        </Section>
      ) : null}

      {sectionVisible("kept") ? (
        <Section
          title={OUTCOME_LABELS.kept}
          count={report.preserved.length}
          tint={OUTCOME_TINT.kept}
          testId="report-section-kept"
        >
          <PreservedBody preserved={report.preserved} />
        </Section>
      ) : null}
    </div>
  );
}

/**
 * The canonical-category view: every row bucketed by its canonical category (Atoms / Cell /
 * Dynamics / …), outcomes mixed inside each category — the same rows, re-organized. The filter
 * narrows rows first, so a category with nothing matching disappears; rows are never dropped.
 */
function CategorySections({
  report,
  rows,
  filter,
}: {
  report: ConversionReport;
  rows: ReportRow[];
  filter: ReportFilter;
}) {
  const sections = groupRowsByCategory(filterRows(rows, filter));
  return (
    <div className="space-y-4">
      {sections.map((section) => (
        <Section
          key={section.key}
          title={section.label}
          count={section.rows.length}
          tint="border-line"
          testId={`report-section-category-${section.key}`}
          wrapList={false}
        >
          <ul className="divide-y divide-line-soft">
            {section.rows.map((row) => (
              <CategoryRow key={row.id} row={row} report={report} />
            ))}
          </ul>
        </Section>
      ))}
    </div>
  );
}
