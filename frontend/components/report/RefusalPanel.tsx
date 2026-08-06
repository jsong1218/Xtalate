import { LossIcon } from "@/components/loss/icons";
import { labelForPath, labelForScenario } from "@/lib/mapping";
import type { ConversionReport, UnresolvedScenario } from "@/lib/report/types";
import { ConversionReportPanel } from "./ConversionReportPanel";

/**
 * A refused conversion (MASTER_SPEC Part 4 §4, rendered per Part 7 §4.5). A refusal is **not an
 * error** — it is a completed job whose `ConversionReport.status === "refused"` (HTTP 200): the
 * engine declined rather than convert with a silent default or an unmade choice. So this panel
 * *heads the same Conversion Report structure* with a refusal banner and then renders the report
 * body underneath — the reader still sees what would have been kept, dropped, and required.
 *
 * Two codes reach here (Part 4 §4):
 *  - `RECOVERY_REQUIRED` — recovery decisions were needed and not supplied; `unresolved_scenarios`
 *    carries each one, its target field, and the honest, pair-specific `options` a caller could pick.
 *  - `UNACKNOWLEDGED_LOSS` — strict mode, reductive loss not acknowledged; `unresolved_scenarios`
 *    is empty (the losses themselves are in the report's Removed section below).
 *
 * Scenario codes resolve to plain labels through `lib/mapping.ts`, machine code one step away — the
 * reader learns *what* is unresolved in their own language before the token they'd pass to the API.
 */
function UnresolvedScenarioRow({ scenario }: { scenario: UnresolvedScenario }) {
  const label = labelForScenario(scenario.scenario);
  return (
    <li data-testid="unresolved-scenario" className="space-y-1 py-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium text-strong">{label.label}</span>
        <code className="rounded bg-cb-fail-bg px-1.5 py-0.5 font-mono text-xs text-cb-fail">
          {scenario.scenario}
        </code>
        {scenario.path ? (
          <span className="text-sm text-muted">→ {labelForPath(scenario.path).label}</span>
        ) : null}
      </div>
      {scenario.detail ? <p className="text-sm text-muted">{scenario.detail}</p> : null}
      {label.description ? <p className="text-sm text-faint">{label.description}</p> : null}
      {scenario.options.length > 0 ? (
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-faint">
          <span>Available choices:</span>
          {scenario.options.map((opt) => (
            <code
              key={opt}
              className="rounded bg-well px-1.5 py-0.5 font-mono text-muted"
            >
              {opt}
            </code>
          ))}
        </p>
      ) : null}
    </li>
  );
}

export function RefusalPanel({ report }: { report: ConversionReport }) {
  const refusal = report.refusal;
  // Defensive: this panel is only meaningful for a refused report. Render nothing rather than a
  // misleading empty banner if a caller routes a non-refusal here.
  if (report.status !== "refused" || refusal === null) return null;

  return (
    <div className="space-y-4">
      <div
        role="alert"
        className="space-y-3 rounded-lg border border-cb-fail bg-cb-fail-bg p-4"
        data-testid="refusal-banner"
      >
        <div className="flex flex-wrap items-center gap-2">
          <LossIcon kind="fail" />
          <h2 className="text-lg font-semibold text-strong">Conversion refused</h2>
          <code className="rounded bg-raised px-1.5 py-0.5 font-mono text-xs font-semibold text-cb-fail">
            {refusal.code}
          </code>
        </div>
        <p className="text-sm text-strong">{refusal.message}</p>

        {refusal.unresolved_scenarios.length > 0 ? (
          <div>
            <h3 className="mb-1 text-sm font-semibold text-body">Needs a decision</h3>
            <ul className="divide-y divide-cb-fail/20">
              {refusal.unresolved_scenarios.map((scenario) => (
                <UnresolvedScenarioRow
                  key={`${scenario.scenario}-${scenario.path ?? ""}`}
                  scenario={scenario}
                />
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {/* The report body still stands: what the refused conversion predicted it would keep and drop. */}
      <ConversionReportPanel report={report} />
    </div>
  );
}
