"use client";

import { useEffect, useRef } from "react";
import { isTerminalJobState } from "@/lib/api/queries";
import { consumeCompletionSignalArm, signalCompletion } from "./completionSignal";
import { useNotifyPreference } from "./NotifyPreferenceProvider";

/**
 * The completion-signal trigger (v1.1 M39-S4, C1): fires `signalCompletion()` (chime +
 * notification) **once** when the watched job makes the non-terminal → terminal transition — but
 * only for a job the user actually launched, and only while the persisted preference is on.
 *
 * Semantics, deliberately narrow:
 *
 *  - **Armed only.** The job page loads cold — its poll query starts `undefined` and resolves to
 *    the real state — so a refresh of (or a shared link to) an already-finished job presents the
 *    same `undefined → terminal` shape as a fresh finish, and under the inline queue the just-
 *    submitted job is already terminal on mount. State alone can't tell them apart, so the Convert
 *    submit *arms* the job id (`armCompletionSignal`) and this hook *consumes* that arm on the
 *    transition. An unarmed job (a reload, a link-open) never fires; the arm is cleared on the
 *    first fire so a later reload of the same job stays silent too.
 *  - **Once.** Refs, not state, so a re-render or a re-poll of a terminal envelope can never
 *    double-fire; React StrictMode's double effect-invocation is guarded the same way. The arm is
 *    consumed at the transition regardless of the toggle, so a stale arm never lingers.
 *  - **Per job.** Keyed by `jobId`, so navigating from one job page to another (the same component
 *    instance reused by the App Router) starts a fresh watch instead of inheriting the previous
 *    job's transition flag.
 *  - **Honors the toggle.** A transition that happens while the preference is off consumes the arm
 *    but signals nothing; unmuting afterwards does not retroactively signal a stale finish.
 *
 * The signal is purely additive: it reports nothing about the science, touches no conversion data,
 * and both channels degrade independently (the module never throws), so the job page's honest
 * completion states are unchanged either way.
 */
export function useCompletionSignal(state: string | undefined, jobId: string): void {
  const { enabled } = useNotifyPreference();
  const watchingRef = useRef<string | null>(null);
  const prevTerminalRef = useRef<boolean | null>(null);

  useEffect(() => {
    // A new job_id starts a fresh watch (component instances may be reused across job pages).
    if (watchingRef.current !== jobId) {
      watchingRef.current = jobId;
      prevTerminalRef.current = null;
    }

    const terminal = state != null && isTerminalJobState(state);
    const prev = prevTerminalRef.current;
    prevTerminalRef.current = terminal;

    if (prev === false && terminal) {
      // Consume the arm at the transition whether or not the signal is enabled, so muting can't
      // leave a stale arm behind — then signal only if the user launched this job and wants it.
      const wasArmed = consumeCompletionSignalArm(jobId);
      if (wasArmed && enabled) signalCompletion();
    }
  }, [state, jobId, enabled]);
}
