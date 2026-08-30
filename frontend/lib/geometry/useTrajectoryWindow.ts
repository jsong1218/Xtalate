"use client";

/**
 * The client-side **sliding-window** trajectory hook (v1.6 M61-S1, D236).
 *
 * The scrubber is a reader over the M59 ranged geometry endpoint
 * (`GET /v1/files/{file_id}/geometry?frames=start:end` /
 * `GET /v1/conversions/{conversion_id}/geometry?side=source|output&frames=start:end` — half-open,
 * 0-based, absolute trajectory positions, D232). It fetches **windows** of frames and keeps a
 * **bounded** set of decoded windows in browser memory (the current window plus room for a
 * prefetched neighbour — {@link MAX_WINDOWS}) — never the whole trajectory, which is exactly the
 * streaming stack's sub-linear-in-frames memory bound inherited client-side (D56 / the M12
 * philosophy, now in the browser; the S3 measurement is the proof it survives).
 *
 * **Frame indices are report indices.** The `frames=start:end` parameter and every `frame.index`
 * in the response are the **absolute** trajectory positions the Discovery/Conversion report names
 * (scrub to *N* ⇒ see frame *N* as the report calls it). The hook works in those absolute indices:
 * `frame` is the absolute index the user has scrubbed to (what the readout shows), and the window
 * it fetches encloses that index. The response's `frame_index_base` equals the window's start (the
 * endpoint sets it from the requested range), so the mount maps an absolute index to a window-local
 * model index without any arithmetic on positions (S2's report-index identity).
 *
 * Memory invariant: the decoded windows handed to the viewer are bounded by {@link MAX_WINDOWS}; a
 * scrub that crosses a window boundary evicts old windows rather than accumulating them. Window
 * fetches also pass `gcTime: 0` so react-query does not retain every distinct window forever (the
 * decoded-frame set fed to Mol* must itself be bounded — that is the memory invariant).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { conversionGeometryQuery, fileGeometryQuery } from "@/lib/api/queries";
import type { CanonicalGeometry } from "./useGeometry";

/** The read target the scrubber windows over — the object the Structure tab already renders. */
export type GeometrySource =
  | { kind: "file"; fileId: string }
  | { kind: "conversion"; conversionId: string; side: "source" | "output" };

/** Frames per window — the decoded-frame window size fed to Mol*. */
export const WINDOW_SIZE = 8;
/** Keep at most this many decoded windows; the current window plus room for a prefetched neighbour. */
export const MAX_WINDOWS = 2;
/**
 * Prefetch the neighbour window when the scrub target is within this many frames of the window's
 * right edge (i.e. during playback, which advances one frame at a time into the next window), so a
 * window boundary crossing does not stall — the next window is already warm in the bounded store.
 */
export const PREFETCH_EDGE = 1;
/**
 * A trajectory is "large" (S3's slower-scrub affordance) when its whole footprint
 * `frame_count × species.length` is at or above this many frame·atoms — the size at which a window
 * re-streams per range rather than serving from the endpoint's byte-bounded cache (the M59-S3
 * latency caveat: ~seconds per window, honestly surfaced, never a hidden stall).
 */
export const LARGE_TRAJECTORY_FRAME_ATOMS = 1_000_000;

/** The `frames=start:end` range string for a half-open window. */
function rangeFor(start: number, end: number): string {
  return `${start}:${end}`;
}

/** The window `[start, end)` (in absolute positions) that encloses `index`. */
function windowEnclosing(index: number, frameCount: number, size: number): { start: number; end: number } {
  const start = Math.floor(index / size) * size;
  const end = Math.min(start + size, frameCount);
  return { start, end };
}

export interface TrajectoryWindow {
  /**
   * The absolute index the user has scrubbed to — the readout shows this, and it equals the
   * report's frame numbering (frame indices are report indices).
   */
  frame: number;
  /**
   * The decoded window geometry whose frames are currently fed to the viewer (bounded). Remains
   * the previous window until the window containing {@link frame} arrives, so the viewer always
   * has a renderable window — a scrub across a window boundary briefly holds the edge frame while
   * the new window loads, never a broken canvas or a fabricated frame.
   */
  currentWindow?: CanonicalGeometry;
  /**
   * The absolute frame index the viewer should display — always within {@link currentWindow}.
   * Equals {@link frame} when that frame is in the held window.
   */
  displayedFrameIndex?: number;
  /** True while a window fetch is in flight. */
  isLoading: boolean;
  /** The most recent window-fetch error (e.g. a mid-scrub 410), if any. */
  error?: unknown;
  /** Request that the scrubber display `index` (absolute); window boundary crossings fetch/evict. */
  ensureFrame: (index: number) => void;
  /**
   * True when the whole object is large (`frame_count × atoms` over the S3 threshold) — the
   * scrubber surfaces an honest "scrubbing may be slower" affordance, never a hidden stall.
   */
  isLarge: boolean;
}

/** A decoded window in the bounded store. */
interface CachedWindow {
  key: string;
  geometry: CanonicalGeometry;
}

/**
 * The sliding-window fetch hook. Give it the read target and the object's whole `frame_count`, and
 * it fetches and holds the window enclosing the currently requested frame.
 */
export function useTrajectoryWindow(
  source: GeometrySource | undefined,
  frameCount: number | undefined,
): TrajectoryWindow {
  const queryClient = useQueryClient();

  // The absolute index the user has scrubbed to (state, for the readout).
  const [frame, setFrame] = useState<number>(0);
  // The decoded window currently fed to the viewer.
  const [currentWindow, setCurrentWindow] = useState<CanonicalGeometry | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<unknown>(undefined);

  const storeRef = useRef<CachedWindow[]>([]);
  const currentKeyRef = useRef<string | null>(null);
  const requestedFrameRef = useRef(0);
  // The windows whose neighbour-prefetch is already in flight (dedupe, never a fetch storm).
  const inflightPrefetchRef = useRef<Set<string>>(new Set());

  const disabled = source === undefined || frameCount === undefined || frameCount < 1;

  /** Skip any window fetch that is already superseded by a newer request. */
  const generationRef = useRef(0);

  /** Fetch one window `[start, end)` and return its geometry (`gcTime: 0` → not retained by react-query). */
  const fetchWindow = useCallback(
    async (start: number, end: number): Promise<CanonicalGeometry> => {
      const range = rangeFor(start, end);
      if (source && source.kind === "conversion") {
        const options = conversionGeometryQuery(source.conversionId, source.side, range);
        return queryClient.fetchQuery({ ...options, gcTime: 0 });
      }
      // `source` is defined (a file) whenever this is reached — the caller gates on `disabled`.
      const options = fileGeometryQuery(source?.fileId ?? "", range);
      return queryClient.fetchQuery({ ...options, gcTime: 0 });
    },
    [queryClient, source],
  );

  /** Adopt a fetched window as the current one, evicting to keep the store bounded. */
  const adoptWindow = useCallback((key: string, geometry: CanonicalGeometry) => {
    setCurrentWindow(geometry);
    currentKeyRef.current = key;
    const store = storeRef.current.filter((w) => w.key !== key); // re-touch: this window is newest
    store.push({ key, geometry });
    while (store.length > MAX_WINDOWS) store.shift(); // evict least-recent window
    storeRef.current = store;
  }, []);

  /** Ensure `index`'s window is the held one; a boundary crossing fetches + adopts (then evicts old). */
  const ensureFrame = useCallback(
    (index: number) => {
      if (disabled) return;
      const n = frameCount as number;
      const clamped = Math.max(0, Math.min(n - 1, index));
      requestedFrameRef.current = clamped;
      setFrame(clamped);
    },
    [disabled, frameCount],
  );

  // The window enclosing the currently requested frame.
  const windowRange = useMemo<{ start: number; end: number } | null>(() => {
    if (disabled) return null;
    return windowEnclosing(frame, frameCount as number, WINDOW_SIZE);
  }, [disabled, frame, frameCount]);
  const windowKey = windowRange ? rangeFor(windowRange.start, windowRange.end) : "";

  // Reconcile: when the requested frame leaves the held window, fetch + adopt the enclosing window.
  useEffect(() => {
    if (!windowRange) return;
    if (currentKeyRef.current === windowKey) return; // already inside the held window

    // Serve from the bounded store when this window was fetched before.
    const cached = storeRef.current.find((w) => w.key === windowKey);
    if (cached) {
      adoptWindow(windowKey, cached.geometry);
      return;
    }

    const generation = ++generationRef.current;
    setIsLoading(true);
    setError(undefined);
    fetchWindow(windowRange.start, windowRange.end)
      .then((geometry) => {
        if (generation !== generationRef.current) return; // superseded
        adoptWindow(windowKey, geometry);
      })
      .catch((err) => {
        if (generation !== generationRef.current) return;
        setError(err);
      })
      .finally(() => {
        if (generation === generationRef.current) setIsLoading(false);
      });
    // `windowKey` is derived from `windowRange`; the reconciliation drives on the target frame.
  }, [windowRange, windowKey, adoptWindow, fetchWindow]);

  // The displayed frame is the scrub target clamped into the held window; while a new window loads
  // it holds the edge frame of the previous window (never a fabricated frame).
  const displayedFrameIndex = useMemo(() => {
    if (!currentWindow) return undefined;
    const base = currentWindow.frame_index_base ?? 0;
    const last = base + (currentWindow.frames?.length ?? 0) - 1;
    if (last < base) return base;
    return Math.max(base, Math.min(last, frame));
  }, [currentWindow, frame]);

  // Prefetch the neighbour window when the target reaches the window's right edge (playback)
  // S3: the next window is fetched into the **bounded** store ahead of the boundary crossing, so
  // scrubbing/playback across an edge does not stall on a cold fetch. It is never adopted or
  // rendered — UI/loading untouched, memory stays at MAX_WINDOWS (the prefetched window is the
  // second slot, so nothing accumulates; a window the user never reaches is evicted by the next
  // adopt).
  useEffect(() => {
    if (!windowRange || disabled) return;
    if (frame < windowRange.end - 1 - PREFETCH_EDGE) return; // not yet on the forward edge
    const nextStart = windowRange.end;
    if (nextStart >= (frameCount as number)) return; // already at the trajectory's end
    const nextEnd = Math.min(nextStart + WINDOW_SIZE, frameCount as number);
    const nextKey = rangeFor(nextStart, nextEnd);
    if (storeRef.current.some((w) => w.key === nextKey)) return; // already warm
    if (inflightPrefetchRef.current.has(nextKey)) return; // already fetching
    inflightPrefetchRef.current.add(nextKey);
    fetchWindow(nextStart, nextEnd)
      .then((geometry) => {
        inflightPrefetchRef.current.delete(nextKey);
        if (storeRef.current.some((w) => w.key === nextKey)) return;
        storeRef.current.push({ key: nextKey, geometry });
        while (storeRef.current.length > MAX_WINDOWS) storeRef.current.shift();
      })
      .catch(() => inflightPrefetchRef.current.delete(nextKey));
  }, [windowRange, frame, frameCount, disabled, fetchWindow]);

  // The "large trajectory — scrubbing may be slower" affordance signal (S3): the whole-object
  // footprint `frame_count × species.length` over the threshold means each window re-streams per
  // range (no cache), which the scrubber surfaces honestly rather than hiding.
  const isLarge = useMemo(() => {
    if (disabled || !frameCount) return false;
    const atoms = currentWindow?.species?.length ?? 0;
    return frameCount * atoms >= LARGE_TRAJECTORY_FRAME_ATOMS;
  }, [disabled, frameCount, currentWindow]);

  return {
    frame: disabled ? 0 : frame,
    currentWindow,
    displayedFrameIndex,
    isLoading,
    error,
    ensureFrame,
    isLarge,
  };
}