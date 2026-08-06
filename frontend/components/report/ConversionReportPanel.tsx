import type { ReactNode } from "react";
import { labelForPath, labelForScenario } from "@/lib/mapping";
import { groupByKey, shouldCollapse } from "@/lib/report/grouping";
import type {
  Assumption,
  ConversionReport,
  RemovedEntry,
  ReportWarning,
  SuppliedEntry,
} from "@/lib/report/types";
import { Row } from "./Row";
import { SummaryChips } from "./SummaryChips";

/**
 * The Conversion Report panel — the five sections of Part 4 §2 rendered in the same order the
 * schema names them: **Preserved, Removed, Supplied + Assumptions, Warnings** (MASTER_SPEC
 * Part 7 §4.3). This is the design-critical surface of v0.6: the whole product promise ("tells you
 * exactly what it kept, what it lost, and why") is this panel being complete and honest.
 *
 * Invariants enforced here:
 *  - **Row completeness.** Each section is `report.<array>.map(...)` — one row per entry, no
 *    filtering, no truncation. A dropped row is a dropped loss, so the tests count rows against the
 *    fixture arrays. Grouping (below) re-parents rows into disclosures but never removes one.
 *  - **Reason verbatim.** A Removed row shows its `reason` string exactly as the engine wrote it,
 *    never a UI paraphrase (Part 7 §2.3).
 *  - **Supplied + Assumptions are adjacent, in the shared ◆ violet, at prominence equal to
 *    Removed** — fabricated data is "a third thing", neither preserved nor lost, and it is never
 *    demoted below the losses it sits beside (Part 7 §4.3). Each Assumption shows its decision
 *    sentence and lists the canonical fields it authorized.
 *  - **Plain language, code one step away.** Field paths and scenario codes resolve through
 *    `lib/mapping.ts`; the raw machine code is never the primary text (Part 7 §3.3).
 *
 * **Readability at scale (addendum S4).** A summary band elevates the count chips to an at-a-glance
 * overview, and the two floodable sections — Warnings, and a lengthy Removed — collapse **same-typed
 * entries into expanded-by-default disclosures** (`lib/report/grouping`): Warnings by `code`, Removed
 * by canonical category. The disclosures start open, so nothing is ever a click away from being seen
 * (the never-buried promise); grouping only kicks in when a key actually repeats, so the ordinary
 * single-warning report stays a flat list. This complements the engine-side D108 frame-range collapse.
 *
 * An empty section is omitted here — the always-present {@link SummaryChips} carry the affirmative
 * zero accounting ("✓ 0 fields removed"), so omission is never a silent blank.
 */

function Section({
  title,
  count,
  tint,
  wrapList = true,
  children,
}: {
  title: string;
  count: number;
  /** Left accent bar color class, bound to a `--cb-*` token. */
  tint: string;
  /** When true (default) the section wraps its rows in a divided `<ul>`; grouped sections manage
   *  their own list/disclosure structure and pass false. */
  wrapList?: boolean;
  children: ReactNode;
}) {
  if (count === 0) return null;
  const headingId = `report-section-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section aria-labelledby={headingId} className={`border-l-2 pl-3 ${tint}`}>
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

/** The top-level canonical category a path belongs to, e.g. `dynamics.forces` → `dynamics`. */
function canonicalCategory(path: string): string {
  const dot = path.indexOf(".");
  return dot === -1 ? path : path.slice(0, dot);
}

/** A canonical category token as a plain heading, e.g. `user_metadata` → "User metadata". */
function categoryLabel(category: string): string {
  const words = category.split("_");
  const [first, ...rest] = words;
  const head = first.charAt(0).toUpperCase() + first.slice(1);
  return [head, ...rest].join(" ");
}

/** A Removed row: field name, then the engine's `reason` verbatim, then any quantitative detail. */
function RemovedRow({ entry }: { entry: RemovedEntry }) {
  return (
    <Row kind="removed" testId="removed-row" label={labelForPath(entry.path).label}>
      <p className="text-sm text-body">{entry.reason}</p>
      {entry.detail ? <p className="text-sm text-muted">{entry.detail}</p> : null}
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

export function ConversionReportPanel({ report }: { report: ConversionReport }) {
  // Group supplied fields under the assumption that authorized each (Part 4 §2 one-to-many).
  const suppliedByAssumption = new Map<string, SuppliedEntry[]>();
  for (const entry of report.supplied) {
    const list = suppliedByAssumption.get(entry.from_assumption) ?? [];
    list.push(entry);
    suppliedByAssumption.set(entry.from_assumption, list);
  }

  // Row completeness is a join-proof invariant: a supplied entry whose `from_assumption` matches
  // no assumption in this report (an engine bug, a hand-edited fixture) must still render — a
  // silently dropped row is a silently dropped loss record.
  const assumptionIds = new Set(report.assumptions.map((a) => a.id));
  const orphanedSupplied = report.supplied.filter((e) => !assumptionIds.has(e.from_assumption));

  const source = report.source;
  const target = report.target;

  return (
    <div className="space-y-4 rounded-lg border border-line p-4">
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
      </header>

      <Section title="Preserved" count={report.preserved.length} tint="border-cb-preserve">
        {report.preserved.map((entry) => (
          <Row
            key={entry.path}
            kind="preserved"
            testId="preserved-row"
            label={labelForPath(entry.path).label}
            detail={entry.detail}
          />
        ))}
      </Section>

      <Section
        title="Removed"
        count={report.removed.length}
        tint="border-cb-removed"
        wrapList={false}
      >
        <RemovedBody removed={report.removed} />
      </Section>

      <Section
        title="Supplied & assumptions"
        count={report.assumptions.length + orphanedSupplied.length}
        tint="border-cb-assumption"
      >
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
      </Section>

      <Section
        title="Warnings"
        count={report.warnings.length}
        tint="border-cb-warning"
        wrapList={false}
      >
        <WarningsBody warnings={report.warnings} />
      </Section>
    </div>
  );
}
