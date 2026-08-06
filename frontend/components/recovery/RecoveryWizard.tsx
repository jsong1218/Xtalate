"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DecisionCard } from "./DecisionCard";
import { Button } from "@/components/ui/Button";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { buildRecoveryBody, isWizardComplete, type WizardState } from "@/lib/recovery/choices";
import { orderedScenarios } from "@/lib/recovery/order";
import { labelForScenario } from "@/lib/mapping";
import {
  previewRecovery as defaultPreview,
  submitRecovery as defaultSubmit,
  type JobEnvelope,
  type RecoveryDecision,
} from "@/lib/api/queries";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import type {
  AwaitingRecoveryBlock,
  ErrorEnvelope as ErrorEnvelopeModel,
} from "@/lib/report/types";

/**
 * The Recovery Workflow wizard (MASTER_SPEC Part 7 §3; slice M31-S1; v0.7 review R1).
 *
 * A paused job's `awaiting_recovery` block carries one unresolved scenario per decision the
 * conversion still owes. The wizard renders a {@link DecisionCard} for each — **in engine resolution
 * order** (`lib/recovery/order.ts`, kept in lockstep with the engine's own published order, so a
 * downstream decision reads below the one it depends on and a parse-time scenario sorts ahead of a
 * conversion-time one), collects the user's `{choice, parameters}` decisions, and turns them into the
 * exact `POST …/recovery` body the engine validated in v0.5. It never invents an option and never
 * preselects one; those invariants live in the card and are proven there.
 *
 * Two engine round-trips, both injectable for tests:
 *  - **preview** (`POST …/recovery/preview`): once every decision is complete (recovery is
 *    all-or-nothing), the wizard fetches the *exact* Assumption sentences the resume would record and
 *    hands each card its own, so the user confirms the real provenance, not a paraphrase (P4).
 *    Confirm is gated on that preview arriving for the *current* choices: consent and provenance are
 *    the same artifact, so a failed or missing preview blocks confirmation and says so — it never
 *    lets the user commit to a record they were never shown.
 *  - **submit** (`POST …/recovery`): on confirm, resumes the job. The result is the server's next
 *    envelope (re-paused or completed) or its error body — an `INVALID_RECOVERY_CHOICE` renders with
 *    its `offered_choices` through the one error component, never coerced.
 *
 * The framing (the deadline, the pre-flight chips) and the first-class "Cancel conversion" decline
 * live in the {@link RecoveryStep} wrapper, so the user is never trapped even when a preview fails.
 */

/** The preview lifecycle for the current complete choice set — the gate on Confirm (P4). */
type PreviewState = "idle" | "loading" | "ready" | "error";

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
  const [previewState, setPreviewState] = useState<PreviewState>("idle");
  const [previewError, setPreviewError] = useState<ErrorEnvelopeModel | null>(null);
  const [previewUnresolved, setPreviewUnresolved] = useState<string[]>([]);
  const [previewNonce, setPreviewNonce] = useState(0);
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
      setPreviewState("idle");
      setPreviewError(null);
      setPreviewUnresolved([]);
      return;
    }
    let cancelled = false;
    setPreviewState("loading");
    setPreviewError(null);
    setPreviewUnresolved([]);
    // Debounced so a live parameter edit does not re-parse the source on every keystroke.
    const handle = setTimeout(async () => {
      const result = await preview(jobId, buildRecoveryBody(stateRef.current));
      if (cancelled) return;
      if (result.ok) {
        // Recovery is all-or-nothing: a complete body should preview every scenario. If the engine
        // still names any `unresolved`, the record is not fully in view — block confirm and say so
        // rather than presenting a partial preview as the whole (P4).
        const unresolved = result.preview.unresolved ?? [];
        if (unresolved.length > 0) {
          setPreviewUnresolved(unresolved);
          setPreviewState("error");
          return;
        }
        const mapped: Record<string, string> = {};
        for (const entry of result.preview.previews ?? []) {
          if (entry.description) mapped[entry.scenario] = entry.description;
        }
        setPreviews(mapped);
        setPreviewState("ready");
      } else {
        setPreviews({});
        setPreviewError(
          toErrorEnvelope(
            result.error,
            "RECOVERY_PREVIEW_FAILED",
            "The exact Assumption text could not be fetched.",
          ),
        );
        setPreviewState("error");
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [bodyKey, previewNonce, jobId, preview]);

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

  const canConfirm = complete && previewState === "ready" && !submitting;

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

      {/* The record must be in view before consent (P4). While it loads, Confirm waits; if it cannot
          be fetched, we say so — nothing has been recorded — and offer a retry, never a silent commit. */}
      {complete && previewState === "loading" ? (
        <p className="text-sm text-muted" data-testid="preview-loading">
          Checking the exact wording that will be recorded…
        </p>
      ) : null}

      {complete && previewState === "error" ? (
        <div
          role="status"
          data-testid="preview-error"
          className="space-y-2 rounded-md border border-cb-assumption bg-cb-assumption-bg p-3"
        >
          <p className="text-sm font-medium text-strong">
            The exact Assumption text could not be fetched — nothing has been recorded, and the
            conversion has not resumed.
          </p>
          {previewUnresolved.length > 0 ? (
            <p className="text-sm text-body">
              The engine still needs a decision for:{" "}
              {previewUnresolved.map((code) => labelForScenario(code).label).join(", ")}.
            </p>
          ) : null}
          {previewError ? <ErrorEnvelope envelope={previewError} /> : null}
          <Button variant="secondary" size="sm" onClick={() => setPreviewNonce((n) => n + 1)}>
            Try previewing again
          </Button>
        </div>
      ) : null}

      {submitError ? <ErrorEnvelope envelope={submitError} /> : null}

      <Button onClick={handleConfirm} disabled={!canConfirm}>
        {submitting ? "Resuming…" : "Confirm and convert"}
      </Button>
    </div>
  );
}
