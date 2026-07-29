"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DecisionCard } from "./DecisionCard";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { buildRecoveryBody, isWizardComplete, type WizardState } from "@/lib/recovery/choices";
import {
  previewRecovery as defaultPreview,
  submitRecovery as defaultSubmit,
  type JobEnvelope,
  type RecoveryDecision,
} from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import type {
  AwaitingRecoveryBlock,
  AwaitingScenario,
  ErrorEnvelope as ErrorEnvelopeModel,
} from "@/lib/report/types";

/**
 * The Recovery Workflow wizard (MASTER_SPEC Part 7 §3; slice M31-S1).
 *
 * A paused job's `awaiting_recovery` block carries one unresolved scenario per decision the
 * conversion still owes. The wizard renders a {@link DecisionCard} for each — **in engine dependency
 * order**, so a downstream decision (the box computed on a chosen frame) reads below the one it
 * depends on — collects the user's `{choice, parameters}` decisions, and turns them into the exact
 * `POST …/recovery` body the engine validated in v0.5. It never invents an option and never
 * preselects one; those invariants live in the card and are proven there.
 *
 * Two engine round-trips, both injectable for tests:
 *  - **preview** (`POST …/recovery/preview`): once every decision is complete (recovery is
 *    all-or-nothing), the wizard fetches the *exact* Assumption sentences the resume would record and
 *    hands each card its own, so the user confirms the real provenance, not a paraphrase (P4).
 *  - **submit** (`POST …/recovery`): on confirm, resumes the job. The result is the server's next
 *    envelope (re-paused or completed) or its error body — an `INVALID_RECOVERY_CHOICE` renders with
 *    its `offered_choices` through the one error component, never coerced.
 *
 * This slice renders the cards, the preview, and the confirm submit; the page framing (the deadline,
 * the pre-flight chips) and the first-class "Cancel conversion" decline are the M31-S2 wrapper.
 */

//: Engine recovery dependency order (`xtalate.recovery.engine._DEP_ORDER`). A scenario the engine
//: does not list (a future plugin's) sorts after the known ones, keeping its block order.
const DEP_ORDER = [
  "frame_selection",
  "constraint_representation",
  "missing_lattice",
  "missing_masses",
  "missing_velocities",
];

function orderedScenarios(scenarios: AwaitingScenario[]): AwaitingScenario[] {
  const rank = (scenario: AwaitingScenario, index: number) => {
    const known = DEP_ORDER.indexOf(scenario.scenario);
    return known === -1 ? DEP_ORDER.length + index : known;
  };
  return scenarios
    .map((scenario, index) => ({ scenario, key: rank(scenario, index) }))
    .sort((a, b) => a.key - b.key)
    .map((entry) => entry.scenario);
}

export function RecoveryWizard({
  block,
  jobId,
  onResumed,
  submit = defaultSubmit,
  preview = defaultPreview,
}: {
  block: AwaitingRecoveryBlock;
  jobId: string;
  /** Called with the server's next envelope after a successful resume (the page re-reads the job). */
  onResumed?: (envelope: JobEnvelope) => void;
  submit?: (
    jobId: string,
    choices: Record<string, RecoveryDecision>,
  ) => Promise<{ ok: true; envelope: JobEnvelope } | { ok: false; error: unknown }>;
  preview?: typeof defaultPreview;
}) {
  const scenarios = useMemo(
    () => orderedScenarios(block.unresolved_scenarios),
    [block.unresolved_scenarios],
  );

  const [state, setState] = useState<WizardState>({});
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<ErrorEnvelopeModel | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const complete = isWizardComplete(scenarios, state);
  // Only re-fetch the preview when the *complete* body changes — an incomplete edit fetches nothing.
  const bodyKey = complete ? JSON.stringify(buildRecoveryBody(state)) : null;
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    if (bodyKey === null) {
      setPreviews({});
      return;
    }
    // Debounced so a live parameter edit does not re-parse the source on every keystroke.
    let cancelled = false;
    const handle = setTimeout(async () => {
      const result = await preview(jobId, buildRecoveryBody(stateRef.current));
      if (cancelled) return;
      if (result.ok) {
        const mapped: Record<string, string> = {};
        for (const entry of result.preview.previews ?? []) {
          if (entry.description) mapped[entry.scenario] = entry.description;
        }
        setPreviews(mapped);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [bodyKey, jobId, preview]);

  const setDecision = (scenario: string, decision: RecoveryDecision) => {
    setState((prev) => ({ ...prev, [scenario]: decision }));
  };

  const handleConfirm = async () => {
    setSubmitError(null);
    setSubmitting(true);
    const result = await submit(jobId, buildRecoveryBody(state));
    setSubmitting(false);
    if (result.ok) {
      onResumed?.(result.envelope);
    } else {
      setSubmitError(
        toErrorEnvelope(result.error, "RECOVERY_FAILED", "The conversion could not be resumed."),
      );
    }
  };

  return (
    <div className="space-y-4" data-testid="recovery-wizard">
      <div className="space-y-3">
        {scenarios.map((scenario) => (
          <DecisionCard
            key={`${scenario.scenario}-${scenario.path ?? ""}`}
            scenario={scenario}
            decision={state[scenario.scenario]}
            preview={previews[scenario.scenario] ?? null}
            onChange={(decision) => setDecision(scenario.scenario, decision)}
          />
        ))}
      </div>

      {submitError ? <ErrorEnvelope envelope={submitError} /> : null}

      <button
        type="button"
        onClick={handleConfirm}
        disabled={!complete || submitting}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {submitting ? "Resuming…" : "Confirm and convert"}
      </button>
    </div>
  );
}
