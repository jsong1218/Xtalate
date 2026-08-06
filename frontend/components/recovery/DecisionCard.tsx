"use client";

import { useState } from "react";
import { LossIcon } from "@/components/loss/icons";
import { AdvisoryNote, type Advisory } from "./AdvisoryNote";
import { AssumptionPreview } from "./AssumptionPreview";
import { ParameterFields } from "./ParameterFields";
import { WhyThisMatters } from "./WhyThisMatters";
import { labelForChoice, labelForPath, labelForScenario } from "@/lib/mapping";
import type { RecoveryDecision } from "@/lib/api/queries";
import type { AwaitingScenario } from "@/lib/report/types";

/**
 * One decision card (MASTER_SPEC Part 7 §3.1–3.2; slice M31-S1).
 *
 * The card renders exactly the options the engine offered for this scenario — it can never present a
 * choice the engine would reject (the options come from the pause's own block) — and reports the
 * user's `{choice, parameters}` decision upward. Two invariants are load-bearing and tested:
 *
 *  1. **No option is preselected** (§3.2). The radios start unchecked; a default with extra steps is
 *     still a default, and this card exists to make the human decide.
 *  2. **The Assumption preview is the record** (§3, P4). When a `preview` sentence is supplied — the
 *     engine's own text for the current choice — it is shown verbatim, so the user confirms the exact
 *     provenance they are creating, not a UI approximation.
 *
 * The card is uncontrolled: it owns the in-progress selection and emits it, so the wizard can lift
 * every card's decision into one state without prop round-trips per keystroke.
 */
export function DecisionCard({
  scenario,
  decision,
  preview,
  advisories,
  onChange,
}: {
  scenario: AwaitingScenario;
  /** An initial selection (e.g. a resumed/reopened card); the card starts unselected without it. */
  decision?: RecoveryDecision;
  /** The engine's exact Assumption sentence for the current choice, or null/absent until previewed. */
  preview?: string | null;
  /**
   * Per-choice advisories, keyed by choice code — the post-1.0 usage-aggregation seam (deliverable 8).
   * Empty on a 1.0 instance, so no note renders; a future slice populates it from the aggregation
   * query. Advisory only: never a default, never a preselection.
   */
  advisories?: Record<string, Advisory>;
  onChange: (decision: RecoveryDecision) => void;
}) {
  const [choice, setChoice] = useState<string | null>(decision?.choice ?? null);
  const [parameters, setParameters] = useState<Record<string, unknown>>(decision?.parameters ?? {});

  const scenarioLabel = labelForScenario(scenario.scenario);
  const selectedOption = scenario.options.find((o) => o.choice === choice);

  const selectChoice = (next: string) => {
    // A new choice starts with fresh parameters — the previous choice's inputs do not carry over.
    setChoice(next);
    setParameters({});
    onChange({ choice: next, parameters: {} });
  };

  const changeParameters = (next: Record<string, unknown>) => {
    setParameters(next);
    if (choice) onChange({ choice, parameters: next });
  };

  return (
    <section
      data-testid="decision-card"
      aria-label={scenarioLabel.label}
      className="space-y-3 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <LossIcon kind="assumption" />
        <h3 className="text-base font-semibold text-strong">{scenarioLabel.label}</h3>
        <code className="rounded bg-cb-assumption-bg px-1.5 py-0.5 font-mono text-xs text-cb-assumption">
          {scenario.scenario}
        </code>
        {scenario.path ? (
          <span className="text-sm text-muted">→ {labelForPath(scenario.path).label}</span>
        ) : null}
      </div>
      {scenarioLabel.description ? (
        <p className="text-sm text-muted">{scenarioLabel.description}</p>
      ) : null}
      {scenario.detail ? <p className="text-sm text-faint">{scenario.detail}</p> : null}

      {/* The scientific stakes, behind a disclosure — a non-expert acts on the options without it,
          and opens it when they want to know what the missing thing is and which choice is safe. */}
      <WhyThisMatters scenario={scenario.scenario} />

      <div role="radiogroup" aria-label={`Options for ${scenarioLabel.label}`} className="space-y-2">
        {scenario.options.map((option) => {
          const params = Object.keys(option.parameters_schema ?? {});
          const active = option.choice === choice;
          return (
            <div key={option.choice} className="rounded-md border border-line p-2">
              <div className="flex items-center gap-2">
                {/* §3.2's card template: the radio reads in plain language, with the machine code kept
                    beside it (§3.3, always correlatable) inside the label so both name the control.
                    The parameter hint sits outside the label so it never bleeds into that name. */}
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`recovery-${scenario.scenario}`}
                    value={option.choice}
                    checked={active}
                    onChange={() => selectChoice(option.choice)}
                  />
                  <span className="text-sm text-strong">
                    {labelForChoice(scenario.scenario, option.choice).label}
                  </span>
                  <code className="rounded bg-well px-1.5 py-0.5 font-mono text-xs text-muted">
                    {option.choice}
                  </code>
                </label>
                {params.length > 0 ? (
                  <span aria-hidden className="text-xs text-faint">
                    needs {params.join(", ")}
                  </span>
                ) : null}
              </div>
              <AdvisoryNote advisory={advisories?.[option.choice]} />
              {active && selectedOption ? (
                <div className="mt-2 pl-6">
                  <ParameterFields
                    option={selectedOption}
                    parameters={parameters}
                    onChange={changeParameters}
                  />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {preview ? <AssumptionPreview description={preview} /> : null}
    </section>
  );
}
