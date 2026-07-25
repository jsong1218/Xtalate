import { LossIcon } from "@/components/loss/icons";
import { ConversionReportPanel } from "@/components/report/ConversionReportPanel";
import { labelForPath, labelForScenario } from "@/lib/mapping";
import type { AwaitingRecoveryBlock, AwaitingScenario } from "@/lib/report/types";

/**
 * The `awaiting_recovery` pause, rendered honestly for v0.6 (MASTER_SPEC Part 6 §3.2; slice M29-S1).
 *
 * The interactive decision cards are v0.7 scope — but the API pauses jobs *today*, so this page must
 * not dead-end. Three rules govern what is shown:
 *
 *  1. **The pause is named, not hidden.** Hiding the state, or auto-cancelling to keep the UI tidy,
 *     would misrepresent a first-class job state. It is shown, in the user's own language, with the
 *     machine code one glance away.
 *  2. **The deadline is stated as what it is.** When `expires_at` passes, the conversion is
 *     **refused for want of a decision** — no default is applied, nothing is fabricated, nothing is
 *     quietly dropped (Part 4 §3.2). The copy here must never read as "we'll pick something."
 *  3. **There is a way forward now.** Every option the engine computed for this concrete
 *     source→target pair is listed with the parameters it takes, plus the CLI and API forms that
 *     accept them — so a caller is not stuck waiting for the next version.
 *
 * The pause's own `draft_report` is rendered underneath: the pre-flight preview of what this
 * conversion would keep and drop once the decisions are made.
 */

/** `POST /v1/jobs/{job_id}/recovery` — the resume endpoint a caller can drive today. */
const RESUME_PATH = (jobId: string) => `POST /v1/jobs/${jobId}/recovery`;

function ScenarioCard({ scenario }: { scenario: AwaitingScenario }) {
  const label = labelForScenario(scenario.scenario);
  return (
    <li data-testid="awaiting-scenario" className="space-y-2 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <LossIcon kind="assumption" />
        <span className="font-medium text-slate-900">{label.label}</span>
        <code className="rounded bg-cb-assumption-bg px-1.5 py-0.5 font-mono text-xs text-cb-assumption">
          {scenario.scenario}
        </code>
        {scenario.path ? (
          <span className="text-sm text-slate-600">→ {labelForPath(scenario.path).label}</span>
        ) : null}
      </div>
      {label.description ? <p className="text-sm text-slate-600">{label.description}</p> : null}
      {/* The engine's own words about this pair — rendered verbatim, never paraphrased. */}
      {scenario.detail ? <p className="text-sm text-slate-500">{scenario.detail}</p> : null}

      <div className="space-y-1">
        <p className="text-xs font-medium text-slate-600">
          Choices available for this conversion — the CLI form is{" "}
          <code className="font-mono">--recover {scenario.scenario}=&lt;choice&gt;</code>
        </p>
        <ul className="space-y-1">
          {scenario.options.map((option) => {
            const params = Object.entries(option.parameters_schema ?? {});
            return (
              <li key={option.choice} className="text-xs text-slate-600">
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-700">
                  {option.choice}
                </code>
                {params.length > 0 ? (
                  <span className="ml-2">
                    takes{" "}
                    {params.map(([name, description], i) => (
                      <span key={name}>
                        {i > 0 ? ", " : ""}
                        <code className="font-mono text-slate-700">{name}</code>
                        <span className="text-slate-500"> ({description})</span>
                      </span>
                    ))}
                  </span>
                ) : (
                  <span className="ml-2 text-slate-500">takes no parameters</span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </li>
  );
}

export function AwaitingRecovery({
  block,
  jobId,
  expiresAt,
}: {
  block: AwaitingRecoveryBlock;
  jobId: string;
  /** The pause's TTL horizon from the job envelope; `null` when the service reported none. */
  expiresAt?: string | null;
}) {
  return (
    <div className="space-y-4">
      <section
        aria-label="Waiting for a decision"
        className="space-y-3 rounded-lg border border-cb-assumption bg-cb-assumption-bg p-4"
        data-testid="awaiting-recovery"
      >
        <div className="flex flex-wrap items-center gap-2">
          <LossIcon kind="assumption" />
          <h2 className="text-lg font-semibold text-slate-900">
            This conversion needs a decision from you
          </h2>
          <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-xs font-semibold text-cb-assumption">
            awaiting_recovery
          </code>
        </div>
        <p className="text-sm text-slate-800">
          The target format needs information this file does not contain. Xtalate has paused rather
          than filling it in, because anything it invented would be data you never supplied.
        </p>

        <ul className="divide-y divide-cb-assumption/20">
          {block.unresolved_scenarios.map((scenario) => (
            <ScenarioCard key={`${scenario.scenario}-${scenario.path ?? ""}`} scenario={scenario} />
          ))}
        </ul>

        {/* Rule 2: the deadline, said plainly — expiry refuses, it does not choose. */}
        <p className="text-sm text-slate-700" data-testid="recovery-deadline">
          {expiresAt ? (
            <>
              This pause is held until{" "}
              <time dateTime={expiresAt} className="font-medium text-slate-900">
                {expiresAt}
              </time>
              .{" "}
            </>
          ) : null}
          If the deadline passes with no choice supplied, the conversion is{" "}
          <strong>refused</strong> — no default is applied and no value is invented. Nothing is
          written until you decide.
        </p>

        <div className="space-y-1 rounded-md bg-white/60 p-3 text-sm text-slate-700">
          <p className="font-medium text-slate-900">Making the choice today</p>
          <p>
            Supply the choices over the API at{" "}
            <code className="font-mono text-xs">{RESUME_PATH(jobId)}</code>, or run the conversion
            from the command line with <code className="font-mono text-xs">--recover</code> presets.
          </p>
          <p className="text-slate-600">
            Choosing these here, in the browser, arrives in the next version.
          </p>
        </div>
      </section>

      {/* What this conversion would keep and drop once the decisions are made. */}
      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-700">
          What this conversion looks like so far
        </h3>
        <ConversionReportPanel report={block.draft_report} />
      </div>
    </div>
  );
}
