"use client";

import { useEffect, useState } from "react";
import type { JobEnvelope } from "@/lib/api/queries";

/**
 * The live phase indicator for a running job (MASTER_SPEC Part 7 §2.4; slice M29-S1).
 *
 * **There is no fake progress bar here, and there must never be one.** The service reports a coarse
 * `progress.phase` and — only for streamed operations that expose them — frame counters; it does
 * not report a percentage. So this component shows exactly what it was told: the phase in plain
 * language, the frame counts *when they exist*, and the elapsed time. An animation easing toward
 * 90% would be the UI inventing a number the engine never produced, which is the same class of
 * dishonesty as a silent default (P1). The one bar that can appear is driven by real
 * `frames_processed / frames_total` values and is labelled with those counts, so what the reader
 * sees is a measurement, not a mood.
 *
 * An unrecognised phase renders its raw code rather than being hidden or guessed at — the same rule
 * `lib/mapping.ts` follows for scenario codes. A new engine phase therefore shows up as an unpolished
 * label, never as a blank indicator.
 */

/** Plain-language names for the phases the worker stamps (`backend/jobs/runner.py`). */
export const PHASE_LABELS: Record<string, string> = {
  parsing: "Reading the source file",
  converting: "Writing the target format",
  validating: "Checking the output against the source",
  recovery: "Working out what decisions are needed",
  done: "Finished",
};

export function phaseLabel(phase: string | null | undefined): string {
  if (!phase) return "Working";
  return PHASE_LABELS[phase] ?? phase;
}

/** `m:ss` (or `h:mm:ss`) from a whole number of seconds. */
export function formatElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const s = String(total % 60).padStart(2, "0");
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/**
 * Seconds between `since` and `now`. Exported so the elapsed rendering is testable without a clock:
 * the component ticks in real time, the unit test passes an explicit `now`.
 */
export function elapsedSeconds(since: string | null | undefined, now: number): number | null {
  if (!since) return null;
  // Job timestamps are UTC; the service serialises them naive (no trailing "Z"), so anchor them
  // explicitly rather than letting the browser read them as local time and report a bogus elapsed.
  const iso = /(Z|[+-]\d{2}:\d{2})$/.test(since) ? since : `${since}Z`;
  const started = Date.parse(iso);
  if (Number.isNaN(started)) return null;
  return (now - started) / 1000;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export function JobPhase({ envelope, now }: { envelope: JobEnvelope; now?: number }) {
  // The clock only runs while the job is live; a fixed `now` makes the rendering deterministic.
  const tick = useNow(now === undefined);
  const at = now ?? tick;

  const progress = envelope.progress;
  const processed = progress?.frames_processed ?? null;
  const total = progress?.frames_total ?? null;
  // A measured fraction — shown only when the engine actually counted frames.
  const hasFrameCounts = typeof processed === "number" && typeof total === "number" && total > 0;
  const elapsed = elapsedSeconds(envelope.started_at ?? envelope.created_at, at);

  return (
    <section aria-label="Job progress" className="space-y-2" data-testid="job-phase">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          aria-hidden="true"
          className="inline-block h-2 w-2 animate-pulse rounded-full bg-cb-assumption"
        />
        <span className="font-medium text-slate-900" role="status">
          {phaseLabel(progress?.phase)}
        </span>
        {progress?.phase ? (
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">
            {progress.phase}
          </code>
        ) : null}
        {elapsed !== null ? (
          <span className="text-sm text-slate-500">{formatElapsed(elapsed)} elapsed</span>
        ) : null}
      </div>

      {hasFrameCounts ? (
        <div className="space-y-1" data-testid="frame-progress">
          <p className="text-sm text-slate-600">
            Frame {processed} of {total}
          </p>
          {/* Width comes from counted frames — the only percentage on this page that was measured. */}
          <div
            role="progressbar"
            aria-valuenow={processed as number}
            aria-valuemin={0}
            aria-valuemax={total as number}
            aria-label="Frames processed"
            className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200"
          >
            <div
              className="h-full rounded-full bg-cb-preserve"
              style={{ width: `${((processed as number) / (total as number)) * 100}%` }}
            />
          </div>
        </div>
      ) : (
        // No counters reported ⇒ no bar at all. Phase and elapsed time are the honest whole truth.
        <p className="text-sm text-slate-500">
          This step does not report frame counts, so there is no progress bar to show.
        </p>
      )}
    </section>
  );
}
