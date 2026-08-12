"use client";

import { useEffect, useRef } from "react";
import { isTerminalJobState } from "@/lib/api/queries";
import { signalCompletion } from "./completionSignal";
import { useNotifyPreference } from "./NotifyPreferenceProvider";

/**
 * The completion-signal trigger (v1.1 M39-S4, C1): fires `signalCompletion()` (chime +
 * notification) **once** when the watched job makes the non-terminal → terminal transition, and
 * only while the persisted preference is on.
 *
 * Semantics, deliberately narrow:
 *
 *  - **Transition only.** A job that *mounts* already terminal (a shared link to a finished job)
 *    is not a transition and never fires — the signal is "it just finished," not "this exists."
 *  - **Once.** Refs, not state, so a re-render or a re-poll of a terminal envelope can never
 *    double-fire; React StrictMode's double effect-invocation is guarded the same way.
 *  - **Per job.** Keyed by `jobId`, so navigating from one job page to another (the same component
 *    instance reused by the App Router) starts a fresh watch instead of inheriting the previous
 *    job's fired flag.
 *  - **Honors the toggle.** A transition that happens while the preference is off fires nothing;
 *    unmuting afterwards does not retroactively signal a stale finish.
 *
 * The signal is purely additive: it reports nothing about the science, touches no conversion data,
 * and both channels degrade independently (the module never throws), so the job page's honest
 * completion states are unchanged either way.
 */
export function useCompletionSignal(state: string | undefined, jobId: string): void {
  const { enabled } = useNotifyPreference();
  const firedForRef = useRef<string | null>(null);
  const prevTerminalRef = useRef<boolean | null>(null);

  useEffect(() => {
    // A new job_id starts a fresh watch (component instances may be reused across job pages).
    if (firedForRef.current !== jobId) {
      firedForRef.current = jobId;
      prevTerminalRef.current = null;
    }

    const terminal = state != null && isTerminalJobState(state);
    const prev = prevTerminalRef.current;
    prevTerminalRef.current = terminal;

    if (prev === false && terminal && enabled) {
      signalCompletion();
    }
  }, [state, jobId, enabled]);
}
