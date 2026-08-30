"use client";

/**
 * The frame scrubber + playback control (v1.6 M61-S1, D236) — Part 7 §6's trajectory-animation row.
 *
 * It is an honest **frame-number** control: the range input's bounds and the readout are the
 * **absolute** indices the report names (frame indices are report indices), and it shows
 * "frame *N* / *M*" — never a time label, because the wire carries no timestep (M59's honesty:
 * XDATCAR etc. number configurations but declare no time axis). Playback advances one frame at a
 * fixed default rate; **speed controls / loop modes are M61's cut line**, not here.
 *
 * Accessibility (the M63 bar, met here): the scrubber is a native `range` input (keyboard
 * operable), and play/pause is a real `button` with `aria-pressed`.
 */
import { useEffect, useState } from "react";

/** Fixed default playback step interval. Speed controls are the S1 cut line, not this value. */
const PLAY_INTERVAL_MS = 600;

export interface TrajectoryScrubberProps {
  /** The object's whole frame count — the *M* of the "frame *N* / *M*" readout. */
  frameCount: number;
  /** The absolute index of the object's first frame (the scrubber's minimum). */
  frameIndexBase: number;
  /** The absolute index currently displayed. */
  frame: number;
  /** Called when the user scrubs or playback advances to `index` (absolute). */
  onScrub: (index: number) => void;
  /** True while a window fetch is in flight (a boundary scrub); surfaced, never a hidden stall. */
  isLoading?: boolean;
  /**
   * True when the whole trajectory is large (M61-S3) — shows the honest "scrubbing may be slower"
   * affordance, never a hidden stall while a window re-streams.
   */
  isLarge?: boolean;
  /**
   * Playback step interval (M61-S3). The production default is {@link PLAY_INTERVAL_MS}; the dev
   * spike harness passes a fast value so a playback heap-measurement journey crosses many windows
   * quickly. Never a production branch — the default keeps the fixed rate everywhere else.
   */
  playIntervalMs?: number;
}

export function TrajectoryScrubber({
  frameCount,
  frameIndexBase,
  frame,
  onScrub,
  isLoading = false,
  isLarge = false,
  playIntervalMs = PLAY_INTERVAL_MS,
}: TrajectoryScrubberProps) {
  const max = frameIndexBase + frameCount - 1;
  const [playing, setPlaying] = useState(false);

  // Playback: while playing, advance one frame per interval until the last frame, then stop.
  useEffect(() => {
    if (!playing) return;
    if (frame >= max) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => onScrub(frame + 1), playIntervalMs);
    return () => clearTimeout(timer);
  }, [playing, frame, max, playIntervalMs, onScrub]);

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-slate-200 bg-slate-50 px-2 py-1.5">
      <button
        type="button"
        aria-pressed={playing}
        onClick={() => setPlaying((v) => !v)}
        className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
      >
        {playing ? "Pause" : "Play"}
      </button>
      <label className="flex items-center gap-2">
        <span className="text-xs text-muted">frame</span>
        <input
          type="range"
          aria-label="Trajectory frame"
          min={frameIndexBase}
          max={max}
          step={1}
          value={frame}
          onChange={(e) => onScrub(Number(e.target.value))}
          className="w-40"
        />
        <span role="status" className="min-w-[5.5rem] text-xs font-medium text-slate-700">
          {frame} / {frameCount}
        </span>
      </label>
      {isLoading ? (
        <span className="text-xs text-muted" data-testid="trajectory-loading">
          loading…
        </span>
      ) : null}
      {isLarge ? (
        <span
          data-testid="trajectory-large"
          className="text-xs text-muted"
          title="Each window of a large trajectory re-streams from the server (a window at a time, never the whole file)."
        >
          Large trajectory — scrubbing may be slower (windows re-stream from the server)
        </span>
      ) : null}
    </div>
  );
}