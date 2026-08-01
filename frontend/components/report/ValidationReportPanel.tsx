import { LossIcon, LossTag, type LossKind } from "@/components/loss/icons";
import { labelForPath } from "@/lib/mapping";
import type { CheckResult, ParseIssue, ValidationReport } from "@/lib/report/types";
import { Row } from "./Row";

/**
 * The Validation Report panel — the post-conversion re-parse-and-diff (MASTER_SPEC Part 5 §3,
 * rendered per Part 7 §4.4). One row per {@link CheckResult}: every check the engine ran *or
 * skipped*, in catalog order. The load-bearing rules:
 *
 *  - **A skipped check is shown, never hidden.** An omitted result would leave a reader guessing
 *    whether fidelity was verified or forgotten, so a `skipped` row renders its `skip_reason`
 *    inline (not behind the disclosure) — the whole point of the report is that absence is stated.
 *  - **Row completeness.** The rows are `checks.map(...)` with no filter; the test counts rows
 *    against `checks.length`, so a dropped check fails loudly.
 *  - **Message verbatim.** Each check's `message` is the engine's own specific, quantitative
 *    sentence — never a UI paraphrase.
 *  - **Numbers one disclosure away.** `measured` and the effective `tolerance_applied` thresholds
 *    (including the representational-precision bound) sit behind a per-row `<details>` — present for
 *    the reader who wants them, out of the way for the reader who does not (Part 7 §3.3).
 *
 * The aggregate `status` (worst individual outcome) heads the panel; `reparse_issues` — warnings
 * raised while re-parsing the output — are a finding in their own right and surface below the checks.
 */

/** Validation check status → the shared §4 loss vocabulary. */
const CHECK_KIND: Record<CheckResult["status"], LossKind> = {
  pass: "preserved",
  warn: "warning",
  fail: "fail",
  skipped: "skipped",
};

/** Aggregate report status → loss vocabulary + a plain-language headline. */
const AGGREGATE: Record<ValidationReport["status"], { kind: LossKind; label: string }> = {
  passed: { kind: "preserved", label: "Validation passed" },
  passed_with_warnings: { kind: "warning", label: "Validation passed with warnings" },
  failed: { kind: "fail", label: "Validation failed" },
};

/** A `measured` / `tolerance_applied` map rendered as a definition list (numbers, one step away). */
function Measurements({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5">
      {entries.map(([key, value]) => (
        <div key={key} className="col-span-2 grid grid-cols-subgrid">
          <dt className="font-mono text-slate-500">{key}</dt>
          <dd className="font-mono break-all text-slate-700">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function CheckRow({ check }: { check: CheckResult }) {
  const kind = CHECK_KIND[check.status];
  const hasNumbers =
    Object.keys(check.measured).length > 0 ||
    (check.tolerance_applied !== null && Object.keys(check.tolerance_applied).length > 0);

  return (
    <Row
      kind={kind}
      testId="check-row"
      label={
        <span className="flex flex-wrap items-center gap-2">
          <code
            className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600"
            title={`check: ${check.check_id}`}
          >
            {check.check_id}
          </code>
          <span className="font-normal text-slate-800">{check.message}</span>
        </span>
      }
    >
      {/* A skipped check states *why* in plain sight — never hidden behind the disclosure. */}
      {check.status === "skipped" && check.skip_reason ? (
        <p className="text-sm text-cb-skipped">Skipped: {check.skip_reason}</p>
      ) : null}

      {check.paths.length > 0 ? (
        <p className="text-xs text-slate-500">
          {check.paths.map((p) => labelForPath(p).label).join(" · ")}
        </p>
      ) : null}

      {hasNumbers ? (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer select-none text-slate-500">
            Measurements &amp; tolerances
          </summary>
          <div className="mt-1 space-y-2">
            <Measurements data={check.measured} />
            {check.tolerance_applied ? (
              <div>
                <p className="mb-0.5 text-slate-500">Tolerance applied</p>
                <Measurements data={check.tolerance_applied} />
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </Row>
  );
}

/** A single re-parse issue raised on the output — Part 3 §5. Warning-severity is the common case. */
function ReparseIssueRow({ issue }: { issue: ParseIssue }) {
  return (
    <Row
      kind={issue.severity === "error" ? "fail" : "warning"}
      testId="reparse-issue-row"
      label={
        <span className="flex flex-wrap items-center gap-2">
          <code className="rounded bg-cb-warning-bg px-1.5 py-0.5 font-mono text-xs text-cb-warning">
            {issue.code}
          </code>
          <span className="font-normal text-slate-800">{issue.message}</span>
        </span>
      }
      detail={issue.location}
    />
  );
}

export function ValidationReportPanel({ report }: { report: ValidationReport }) {
  const aggregate = AGGREGATE[report.status];
  const profileName =
    typeof report.tolerance_profile.name === "string" ? report.tolerance_profile.name : null;

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 p-4">
      <header className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">Validation report</h2>
        <LossTag kind={aggregate.kind}>{aggregate.label}</LossTag>
        {profileName ? (
          <p className="text-xs text-slate-500">
            Tolerance profile:{" "}
            <code className="font-mono text-slate-600">{profileName}</code>
          </p>
        ) : null}
      </header>

      <section aria-label="Checks">
        <ul className="divide-y divide-slate-100">
          {report.checks.map((check, i) => (
            // `check_id`-plus-index, like `reparse_issues` below: a `check_id` alone is not
            // guaranteed unique (a trajectory can run the same catalog check per frame), and a
            // duplicate React key silently drops rows — a reported check must never be lost to a
            // key collision (the v0.7 review). Rows are still in stable catalog order.
            <CheckRow key={`${check.check_id}-${i}`} check={check} />
          ))}
        </ul>
      </section>

      {report.reparse_issues.length > 0 ? (
        <section aria-labelledby="reparse-heading" className="border-l-2 border-cb-warning pl-3">
          <h3 id="reparse-heading" className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-slate-700">
            <LossIcon kind="warning" /> Re-parse issues
            <span className="font-normal text-slate-500">({report.reparse_issues.length})</span>
          </h3>
          <ul className="divide-y divide-slate-100">
            {report.reparse_issues.map((issue, i) => (
              <ReparseIssueRow key={`${issue.code}-${i}`} issue={issue} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
