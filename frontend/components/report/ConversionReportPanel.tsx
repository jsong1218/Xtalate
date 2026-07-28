import type { ReactNode } from "react";
import { labelForPath, labelForScenario } from "@/lib/mapping";
import type {
  Assumption,
  ConversionReport,
  RemovedEntry,
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
 *    fixture arrays.
 *  - **Reason verbatim.** A Removed row shows its `reason` string exactly as the engine wrote it,
 *    never a UI paraphrase (Part 7 §2.3).
 *  - **Supplied + Assumptions are adjacent, in the shared ◆ violet, at prominence equal to
 *    Removed** — fabricated data is "a third thing", neither preserved nor lost, and it is never
 *    demoted below the losses it sits beside (Part 7 §4.3). Each Assumption shows its decision
 *    sentence and lists the canonical fields it authorized.
 *  - **Plain language, code one step away.** Field paths and scenario codes resolve through
 *    `lib/mapping.ts`; the raw machine code is never the primary text (Part 7 §3.3).
 *
 * An empty section is omitted here — the always-present {@link SummaryChips} carry the affirmative
 * zero accounting ("✓ 0 fields removed"), so omission is never a silent blank.
 */

function Section({
  title,
  count,
  tint,
  children,
}: {
  title: string;
  count: number;
  /** Left accent bar color class, bound to a `--cb-*` token. */
  tint: string;
  children: ReactNode;
}) {
  if (count === 0) return null;
  const headingId = `report-section-${title.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return (
    <section aria-labelledby={headingId} className={`border-l-2 pl-3 ${tint}`}>
      <h3 id={headingId} className="mb-1 text-sm font-semibold text-slate-700">
        {title} <span className="font-normal text-slate-500">({count})</span>
      </h3>
      <ul className="divide-y divide-slate-100">{children}</ul>
    </section>
  );
}

/** A Removed row: field name, then the engine's `reason` verbatim, then any quantitative detail. */
function RemovedRow({ entry }: { entry: RemovedEntry }) {
  return (
    <Row kind="removed" testId="removed-row" label={labelForPath(entry.path).label}>
      <p className="text-sm text-slate-700">{entry.reason}</p>
      {entry.detail ? <p className="text-sm text-slate-600">{entry.detail}</p> : null}
    </Row>
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
            <li key={entry.path} data-testid="supplied-row" className="text-sm text-slate-600">
              <span className="text-cb-assumption">+ </span>
              {labelForPath(entry.path).label}
              {entry.detail ? <span className="text-slate-500"> — {entry.detail}</span> : null}
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
    <div className="space-y-4 rounded-lg border border-slate-200 p-4">
      <header className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">Conversion report</h2>
        <p className="text-sm text-slate-600">
          <span className="font-medium text-slate-800">{source.filename}</span>{" "}
          <span className="text-slate-500">({source.format_id})</span>
          <span aria-hidden="true"> → </span>
          <span className="font-medium text-slate-800">{target.filename}</span>{" "}
          <span className="text-slate-500">({target.format_id})</span>
          <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
            {report.mode}
          </span>
        </p>
        <SummaryChips report={report} />
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

      <Section title="Removed" count={report.removed.length} tint="border-cb-removed">
        {report.removed.map((entry, i) => (
          <RemovedRow key={`${entry.path}-${i}`} entry={entry} />
        ))}
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
                <li key={entry.path} data-testid="supplied-row" className="text-sm text-slate-600">
                  <span className="text-cb-assumption">+ </span>
                  {labelForPath(entry.path).label}
                  {entry.detail ? <span className="text-slate-500"> — {entry.detail}</span> : null}
                </li>
              ))}
            </ul>
          </Row>
        ) : null}
      </Section>

      <Section title="Warnings" count={report.warnings.length} tint="border-cb-warning">
        {report.warnings.map((warning, i) => (
          <Row
            key={`${warning.code}-${i}`}
            kind="warning"
            testId="warning-row"
            label={
              <span className="flex flex-wrap items-center gap-2">
                <code
                  className="rounded bg-cb-warning-bg px-1.5 py-0.5 text-xs text-cb-warning"
                  title={`source: ${warning.source}`}
                >
                  {warning.code}
                </code>
                <span className="font-normal text-slate-800">{warning.message}</span>
              </span>
            }
          />
        ))}
      </Section>
    </div>
  );
}
