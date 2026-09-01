"use client";

/**
 * StructureViewer (v1.6 M59-S2, extended M61-S1) — the reusable Mol\\* mount atom that M60's tab,
 * M61's scrubber, and M62's Compare each consume. Built standalone, not welded to a page.
 *
 * SSR safety: the Mol\\* plugin is WebGL/canvas and client-only, so the actual mount lives in a
 * dynamically-imported `ssr: false` chunk (`StructureViewerMolstar`) — the production build never
 * evaluates the plugin on the server (D98).
 *
 * Bonds policy (D234): the loader attaches no bond data and the mount draws an atoms-only
 * representation, so bonds are **off by default**. The toggle only exposes the persistent
 * heuristic badge — bonds are a display inference, never file content, and no report mentions
 * them.
 *
 * **M61-S1 (D236):** when the geometry is a multi-frame trajectory (`frame_count > 1`) and the
 * caller supplies a read `trajectorySource`, the viewer renders the frame scrubber + playback and
 * feeds the mount through a **client-side sliding window** (`useTrajectoryWindow`) — a bounded set
 * of decoded frames fetched over the M59 ranged endpoint, never the whole trajectory. Single-frame
 * objects render exactly as M60 shipped (static, no scrubber) — and because the window hook only
 * mounts for a multi-frame object, the single-frame render path stays react-query-free.
 */
import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";
import {
  useTrajectoryWindow,
  type GeometrySource,
} from "@/lib/geometry/useTrajectoryWindow";
import { TrajectoryScrubber } from "./TrajectoryScrubber";
import { LossTag } from "@/components/loss/icons";
import { StructureLegend } from "./StructureLegend";
import type { CameraControls, ViewerControls } from "./StructureViewerMolstar";

const MolstarView = dynamic(() => import("./StructureViewerMolstar"), {
  ssr: false,
  // The loading affordance uses the `text-muted` token (not a raw slate shade): the Structure tab
  // mounts this viewer on axe-scanned pages, and the placeholder must clear the AA contrast bar on
  // both surfaces (v1.6 M60-S1 — found by the e2e accessibility journey on the conversion page).
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-muted">
      Loading structure…
    </div>
  ),
});

/**
 * The supplied-geometry violet badge (v1.6 M60-S3, D235): when a rendered quantity's canonical
 * path appears in `conversion_report.supplied`, the viewer marks it in the ◆ `text-cb-assumption`
 * violet of the loss language — a fabricated lattice looks different from a source lattice
 * everywhere it appears — with its Assumption **one click away**. The fact is report-sourced by the
 * caller (`StructureTab` reads `supplied[].path` + `from_assumption`); this component only renders
 * it.
 */
export interface SuppliedCell {
  /** The `Assumption.id` that authorized the fabricated cell (`supplied[].from_assumption`). */
  fromAssumption: string;
  /** The assumption's recorded `description`, when the report resolves it. */
  description?: string;
}

const BONDS_HEURISTIC_BADGE =
  "Bonds are a display heuristic, not file content";

/**
 * The cell-less caption (v1.6 M60-S2, P3): when the geometry declares no cell, the atoms render in
 * open space with an explicit "no simulation cell" caption and **no box** — the tab never draws a
 * fabricated box around cell-less data. The endpoint answers `cell: null` (D232), and this caption
 * must always agree with the files page's inventory (both say "no cell" for the same file).
 */
const NO_CELL_CAPTION =
  "This file declares no simulation cell — the atoms render in open space, with no box.";

export interface StructureViewerProps {
  geometry: CanonicalGeometry;
  /** Optional label shown above the viewport (e.g. the source filename). */
  label?: string;
  /**
   * Present when the rendered cell was **supplied by recovery** (D235): the wireframe draws violet
   * and the badge names its Assumption. Report-sourced by the caller — never derived here.
   */
  suppliedCell?: SuppliedCell | null;
  /**
   * When present, the viewer windows over this read target for a multi-frame object (`frame_count
   * > 1`): the same M59 geometry the tab already renders (a file's frames, or a conversion's
   * source/output). Single-frame objects ignore it.
   */
  trajectorySource?: GeometrySource;
  /**
   * Playback step interval (M61-S3): the production default is the fixed 600 ms; the dev spike
   * surface passes a fast value so a playback heap-measurement journey is quick. Never threaded by
   * a production caller.
   */
  playIntervalMs?: number;
  /**
   * Additive camera-lock seam (M62-S1, D239): when present, the viewer's plugin camera is handed
   * upward on mount so a parent (the Compare tab) can lock two viewers together. A lone viewer
   * passes nothing and behaves exactly as it does today.
   */
  cameraControls?: CameraControls;
  /**
   * Controlled-frame mode (M62-S1): when present, the parent owns the shared scrubber and tells
   * this viewer which **absolute** report index to display. The viewer renders **no scrubber of
   * its own** and windows over `trajectorySource` to show `frameControl.frame` — one scrubber in
   * the Compare tab drives both sides (honest frame-lock: only where the frame counts match, by the
   * caller's decision).
   */
  frameControl?: { frame: number };
}

/**
 * The multi-frame trajectory mount (M61-S1, extended M62-S1): owns the sliding-window hook and,
 * in the standalone (Structure-tab) path, the frame scrubber; in controlled mode (Compare) the
 * parent's scrubber drives `frameControl.frame` and no local scrubber renders — one scrubber, no
 * fork.
 */
function TrajectoryViewer({
  geometry,
  suppliedCell,
  trajectorySource,
  cameraControls,
  bonds,
  viewerControls,
  playIntervalMs,
  frameControl,
}: {
  geometry: CanonicalGeometry;
  suppliedCell?: boolean;
  trajectorySource: GeometrySource;
  cameraControls?: CameraControls;
  bonds?: boolean;
  viewerControls?: ViewerControls;
  playIntervalMs?: number;
  frameControl?: { frame: number };
}) {
  const trajectory = useTrajectoryWindow(trajectorySource, geometry.frame_count);
  // Controlled mode (M62-S1): the parent owns the frame; drive the sliding window to it. The hook's
  // `ensureFrame` is stable per `frame_count`, so this effect only re-runs on an actual frame change.
  useEffect(() => {
    if (frameControl) trajectory.ensureFrame(frameControl.frame);
    // Deps are keyed on the frame number (not the `frameControl` object or the whole hook result)
    // so the window only re-targets on an actual frame move; `ensureFrame` is stable per frame_count.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frameControl?.frame, trajectory.ensureFrame]);
  // The window's geometry when loaded, else the static frame (first paint); always an absolute index.
  const mountGeometry = trajectory.currentWindow ? trajectory.currentWindow : geometry;
  const mountFrame =
    trajectory.displayedFrameIndex !== undefined
      ? trajectory.displayedFrameIndex
      : geometry.frame_index_base ?? 0;

  return (
    <>
      {frameControl ? null : (
        <TrajectoryScrubber
          frameCount={geometry.frame_count}
          frameIndexBase={geometry.frame_index_base ?? 0}
          frame={trajectory.frame}
          onScrub={trajectory.ensureFrame}
          isLoading={trajectory.isLoading}
          isLarge={trajectory.isLarge}
          playIntervalMs={playIntervalMs}
        />
      )}
      <MolstarView
        geometry={mountGeometry}
        frameIndex={mountFrame}
        suppliedCell={suppliedCell}
        cameraControls={cameraControls}
        bonds={bonds}
        viewerControls={viewerControls}
      />
      {trajectory.error ? (
        <p role="status" className="text-xs text-muted" data-testid="trajectory-error">
          Could not load this frame window from the server.
        </p>
      ) : null}
    </>
  );
}

export function StructureViewer({
  geometry,
  label,
  suppliedCell,
  trajectorySource,
  cameraControls,
  playIntervalMs,
  frameControl,
}: StructureViewerProps) {
  const [bondsEnabled, setBondsEnabled] = useState(false);
  const [expanded, setExpanded] = useState(false);
  // Stable across re-renders (fix round 1, finding 2): `FullscreenViewer`'s mount effect depends
  // on `onClose` to capture/restore focus and wire the Escape listener exactly once per open. An
  // inline `() => setExpanded(false)` is a fresh closure every render, so any re-render of this
  // component while expanded (a bonds toggle, a trajectory frame tick during Compare playback)
  // would tear down and re-run that effect — re-stealing focus and corrupting the "restore to the
  // true opener" guarantee. `setExpanded` from `useState` is itself stable, so wrapping it with an
  // empty dependency array is sufficient.
  const closeOverlay = useCallback(() => setExpanded(false), []);
  const resetRef = useRef<(() => void) | null>(null);
  const viewerControls = useMemo(
    () => ({
      onReady(controls: { resetCamera(): void }) {
        resetRef.current = controls.resetCamera;
        return () => {
          resetRef.current = null;
        };
      },
    }),
    [],
  );
  const multiFrame =
    geometry.frame_count > 1 && trajectorySource !== undefined;

  const viewerBody = (
    <>
      {multiFrame && trajectorySource ? (
        <TrajectoryViewer
          geometry={geometry}
          suppliedCell={Boolean(suppliedCell)}
          trajectorySource={trajectorySource}
          cameraControls={cameraControls}
          bonds={bondsEnabled}
          viewerControls={viewerControls}
          playIntervalMs={playIntervalMs}
          frameControl={frameControl}
        />
      ) : (
        <MolstarView
          geometry={geometry}
          frameIndex={geometry.frame_index_base ?? 0}
          suppliedCell={Boolean(suppliedCell)}
          cameraControls={cameraControls}
          bonds={bondsEnabled}
          viewerControls={viewerControls}
        />
      )}
      {bondsEnabled ? (
        <div
          role="status"
          className="absolute bottom-2 left-2 rounded bg-bonds-bg px-2 py-1 text-xs text-bonds-fg"
        >
          {BONDS_HEURISTIC_BADGE}
        </div>
      ) : null}
    </>
  );

  return (
    <div className="grid grid-rows-[auto_auto_auto] gap-2">
      <div data-testid="viewer-annotations" className="space-y-2">
        {label ? (
          <div className="text-xs font-medium text-muted">{label}</div>
        ) : null}
        {suppliedCell ? (
          <div
            data-testid="supplied-lattice"
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-cb-assumption bg-cb-assumption-bg px-2 py-1.5"
          >
            <LossTag kind="assumption">This lattice was supplied by recovery</LossTag>
            <a
              href={`#assumption-${suppliedCell.fromAssumption}`}
              className="text-xs font-medium text-cb-assumption underline"
            >
              See Assumption {suppliedCell.fromAssumption}
            </a>
          </div>
        ) : null}
        <StructureLegend species={geometry.species} />
        {geometry.cell == null ? (
          <p data-testid="no-cell-caption" className="text-xs text-muted">
            {NO_CELL_CAPTION}
          </p>
        ) : null}
      </div>
      <div
        data-testid="viewer-canvas"
        className="relative h-96 w-full overflow-hidden rounded border border-line"
      >
        {expanded ? (
          <div className="h-full w-full" />
        ) : (
          viewerBody
        )}
      </div>
      {expanded ? (
        <FullscreenViewer onClose={closeOverlay}>{viewerBody}</FullscreenViewer>
      ) : null}
      <div data-testid="viewer-controls" className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-pressed={bondsEnabled}
          onClick={() => setBondsEnabled((v) => !v)}
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:bg-raised"
        >
          {bondsEnabled ? "Hide bonds heuristic" : "Show bonds heuristic"}
        </button>
        <button
          type="button"
          onClick={() => resetRef.current?.()}
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:bg-raised"
        >
          Reset view
        </button>
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:bg-raised"
        >
          Expand
        </button>
      </div>
    </div>
  );
}

/**
 * Standard focusable selector for the trap below — mirrors what `CommandPalette`'s trap ultimately
 * targets (its own `input` + `[data-result-row]` buttons are a subset of this), generalized because
 * `FullscreenViewer`'s children are arbitrary (the Close button, plus whatever `viewerBody` renders
 * — e.g. a trajectory scrubber's play/seek controls).
 */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The expand overlay (D-next): a fixed-inset dialog that hosts the same `viewerBody` full-screen.
 * Focus moves onto the dialog on open and returns to the previously focused element on close, and
 * Escape closes it — the axe-scanned pages this viewer mounts on hold serious+critical to zero, so
 * the dialog carries an accessible name (`aria-label`) rather than relying on visible text alone.
 *
 * Fix round 1 (findings 1 + 2): the dialog now implements a **real** focus trap, not just an
 * initial focus call — Tab/Shift+Tab cycle only among the dialog's own focusable elements (the
 * same event-capture pattern `CommandPalette`'s `trapTab` uses: intercept Tab, `preventDefault`,
 * and move focus manually — reused here for consistency rather than introducing a second trap
 * convention). Because every Tab press inside the dialog is caught and redirected, the sibling
 * `viewer-controls` row mounted behind the `z-50` overlay is never reachable by keyboard, with no
 * need for `inert`/`aria-hidden` on the background (the codebase has no such convention either —
 * the palette doesn't use it, so neither does this). `onClose` must be a **stable** callback (the
 * caller now wraps it in `useCallback`) so this mount effect — which captures the pre-open focus
 * target and wires the Escape/close-on-unmount handling — runs exactly once per open rather than
 * re-running (and re-stealing focus) on every incidental re-render of the parent while expanded.
 */
function FullscreenViewer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);

  function trapTab(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Tab") return;
    const container = ref.current;
    if (!container) return;
    const focusables = Array.from(
      container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    );
    if (focusables.length === 0) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    const idx = focusables.indexOf(document.activeElement as HTMLElement);
    const nextIdx = e.shiftKey
      ? idx <= 0
        ? focusables.length - 1
        : idx - 1
      : (idx + 1) % focusables.length;
    focusables[nextIdx].focus();
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal="true"
      aria-label="Structure viewer"
      tabIndex={-1}
      onKeyDown={trapTab}
      className="fixed inset-0 z-50 flex flex-col bg-surface p-4 outline-none"
    >
      <div className="mb-2 flex justify-end">
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:bg-raised"
        >
          Close
        </button>
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden rounded border border-line">
        {children}
      </div>
    </div>
  );
}