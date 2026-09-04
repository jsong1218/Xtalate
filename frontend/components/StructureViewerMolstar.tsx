"use client";

/**
 * The Mol\\* mount (v1.6 M59-S2, extended M61-S1, M61 review #2) — the `ssr: false` dynamic chunk
 * behind `StructureViewer`. This module pulls the WebGL plugin and must never be evaluated during
 * server rendering; it is only ever loaded through the viewer's dynamic import.
 *
 * The mount is driven by two pieces: the **window geometry** (the bounded set of decoded frames the
 * scrubber hands over) and the **absolute** report index to display. The plugin is mounted **once**
 * (a `suppliedCell` change — the unit-cell color, fixed at mount — re-mounts, but that never changes
 * during playback). From there:
 *  - a frame *change within* the window calls the mount's cheap `setFrame` (the `ModelFromTrajectory`
 *    `modelIndex` update — no rebuild);
 *  - a *window change* calls `setWindow`, which rebuilds only the trajectory subtree **in place** —
 *    the plugin, canvas, and camera survive, so continuous playback across window boundaries neither
 *    flashes nor loses the viewer's rotation/zoom (review #2, replacing the per-window re-mount).
 *
 * Both paths redraw that frame's unit-cell wireframe (variable-cell trajectories breathe; a cell-less
 * frame draws no box — `data-unitcell-drawn` stays honest per displayed frame).
 */
import { useCallback, useEffect, useRef } from "react";
import {
  mountStructureViewer,
  type MountedStructureViewer,
  type StructureViewerCamera,
} from "@/lib/geometry/molstarMount";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";
import { useOptionalTheme, type Theme } from "@/lib/theme/ThemeProvider";

/**
 * The renderer background per theme (D-next): keeps the WebGL canvas in step with the app's
 * light/dark palette instead of Mol*'s own default background. Read once at mount time (via a
 * ref, since the mount effect depends only on `suppliedCell`) and reconciled afterward through
 * `handle.setBackground` on every theme change.
 */
const THEME_BG: Record<Theme, number> = { light: 0xffffff, dark: 0x0f172a };

/**
 * The additive camera-lock seam (M62-S1, D239): when present, the parent hands the mount's camera
 * (`handle.camera`) upward once the plugin is mounted, so the Compare tab can lock two viewers
 * together. A lone Structure-tab viewer (M60) passes nothing and behaves exactly as before — the
 * seam is optional and never mounted in the single-viewer path.
 */
export interface CameraControls {
  /** Called with the viewer's camera controls once the plugin mount resolves; returns an unsubscribe. */
  onReady(camera: StructureViewerCamera): () => void;
}

/**
 * The additive reset-control seam (D-next): mirrors {@link CameraControls} but hands up only the
 * `resetCamera` action, so a parent that just wants a "reset view" button need not thread the
 * full camera get/set/observe surface. A lone viewer passes nothing.
 */
export interface ViewerControls {
  /** Called with `{ resetCamera }` once the plugin mount resolves; returns an unsubscribe. */
  onReady(controls: { resetCamera(): void }): () => void;
}

export default function StructureViewerMolstar({
  geometry,
  frameIndex,
  suppliedCell,
  cameraControls,
  bonds,
  viewerControls,
}: {
  geometry: CanonicalGeometry;
  /** The absolute report index to display (defaults to the geometry's frame_index_base). */
  frameIndex?: number;
  /** When true the unit-cell wireframe is drawn in the supplied-violet (D235). */
  suppliedCell?: boolean;
  /** Additive camera-lock seam (M62-S1): surfaced to its parent on mount, if supplied. */
  cameraControls?: CameraControls;
  /** Toggle the heuristic ball-and-stick bond visual (D234/D-next). */
  bonds?: boolean;
  /** Additive reset-control seam: surfaced to its parent on mount, if supplied. */
  viewerControls?: ViewerControls;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<MountedStructureViewer | null>(null);
  // The window identity + frame the mount currently shows, and the window a swap is applying.
  const mountedGeoRef = useRef<string | null>(null);
  const mountedFrameRef = useRef<number | null>(null);
  const windowInFlightRef = useRef<string | null>(null);

  // Latest props mirrored into refs so the mount effect (which runs on `suppliedCell` only) and the
  // async reconcilers always read the current window/frame, never a stale mount-time value.
  const geometryJson = JSON.stringify(geometry);
  const geometryJsonRef = useRef(geometryJson);
  geometryJsonRef.current = geometryJson;
  const geometryRef = useRef(geometry);
  geometryRef.current = geometry;

  const frame = frameIndex ?? geometry.frame_index_base ?? 0;
  const frameRef = useRef(frame);
  frameRef.current = frame;

  // The theme-aware background (D-next): read via `useOptionalTheme` (non-throwing — this mount
  // renders under a bare `render()` in unit tests, with no ThemeProvider above it) and mirrored
  // into a ref so the mount effect (which runs on `suppliedCell` only) reads the current value
  // at mount time without becoming a dependency that would re-mount the plugin on every toggle.
  const theme = useOptionalTheme();
  const themeRef = useRef(theme);
  themeRef.current = theme;

  // Mirror the bonds prop into a ref for the same reason (applied at mount, reconciled below).
  const bondsRef = useRef(bonds);
  bondsRef.current = bonds;

  // Mirror the camera-controls prop into a ref so the mount effect (which runs on `suppliedCell`
  // only) always reads the latest seam without becoming a dependency that re-mounts the plugin.
  const cameraControlsRef = useRef(cameraControls);
  cameraControlsRef.current = cameraControls;
  // The unsubscribe the camera seam returned from `onReady`; called on unmount/re-mount.
  const cameraWriteupRef = useRef<(() => void) | null>(null);

  // Mirror the viewer-controls (reset seam) prop the same way as cameraControls.
  const viewerControlsRef = useRef(viewerControls);
  viewerControlsRef.current = viewerControls;
  // The unsubscribe the viewer-controls seam returned from `onReady`; called on unmount/re-mount.
  const viewerWriteupRef = useRef<(() => void) | null>(null);
  // A frame-only change within the mounted window: cheap in-place frame set (no rebuild). Skips
  // when the window is not yet the mounted one (the window swap below sets the frame on arrival).
  const applyFrame = useCallback(async () => {
    const handle = handleRef.current;
    if (!handle) return;
    if (mountedGeoRef.current !== geometryJsonRef.current) return;
    const target = frameRef.current;
    if (mountedFrameRef.current === target) return;
    mountedFrameRef.current = target;
    await handle.setFrame(target).catch((err) => {
      console.error("Mol* setFrame failed:", err);
    });
  }, []);

  // A window change: swap the frame set in place (plugin + camera preserved). Deduped against the
  // window already shown and the one already applying; reconciles again if a newer window/frame
  // arrived while applying, so the latest state always wins.
  const applyWindow = useCallback(
    async function applyWindow(): Promise<void> {
      const handle = handleRef.current;
      if (!handle) return;
      const targetJson = geometryJsonRef.current;
      if (mountedGeoRef.current === targetJson) return; // already shown
      if (windowInFlightRef.current === targetJson) return; // already applying
      windowInFlightRef.current = targetJson;
      const targetGeometry = geometryRef.current;
      const targetFrame = frameRef.current;
      await handle.setWindow(targetGeometry, targetFrame).catch((err) => {
        console.error("Mol* setWindow failed:", err);
      });
      mountedGeoRef.current = targetJson;
      mountedFrameRef.current = targetFrame;
      if (windowInFlightRef.current === targetJson) windowInFlightRef.current = null;
      if (containerRef.current) containerRef.current.dataset.currentFrame = String(targetFrame);
      // A newer window/frame may have arrived mid-swap — reconcile to it.
      if (geometryJsonRef.current !== mountedGeoRef.current) void applyWindow();
      else if (frameRef.current !== mountedFrameRef.current) void applyFrame();
    },
    [applyFrame],
  );

  // Mount the plugin once (a `suppliedCell` change re-mounts — the unit-cell color is fixed at
  // mount and never changes during playback). Window/frame changes are handled in place below.
  useEffect(() => {
    const target = containerRef.current;
    if (!target) return;
    let cancelled = false;
    if (handleRef.current) {
      try {
        handleRef.current.dispose();
      } finally {
        handleRef.current = null;
      }
    }
    mountedGeoRef.current = null;
    windowInFlightRef.current = null;
    target.dataset.mounted = "false";
    const mountGeometry = geometryRef.current;
    const mountFrame = frameRef.current;
    target.dataset.currentFrame = String(mountFrame);

    void mountStructureViewer(target, mountGeometry, {
      suppliedCell: Boolean(suppliedCell),
      initialFrameIndex: mountFrame,
      backgroundColor: THEME_BG[themeRef.current],
    })
      .then((handle) => {
        if (cancelled) {
          handle.dispose();
          return;
        }
        handleRef.current = handle;
        mountedGeoRef.current = JSON.stringify(mountGeometry);
        mountedFrameRef.current = mountFrame;
        target.dataset.mounted = "true";
        // The additive camera-lock seam (M62-S1): hand the mount's camera upward so the Compare tab
        // can broadcast it to the sibling viewer (the mount already exposes get/set/observe). The
        // returned unsubscribe is released on unmount/re-mount below.
        cameraWriteupRef.current?.();
        cameraWriteupRef.current =
          cameraControlsRef.current?.onReady(handle.camera) ?? null;
        // The additive reset-control seam: hand `resetCamera` upward the same way.
        viewerWriteupRef.current?.();
        viewerWriteupRef.current =
          viewerControlsRef.current?.onReady({ resetCamera: () => handle.resetCamera() }) ?? null;
        if (bondsRef.current) void handle.setBonds(true);
        // A window/frame changed while the plugin was mounting → reconcile now.
        if (geometryJsonRef.current !== mountedGeoRef.current) void applyWindow();
        else if (frameRef.current !== mountedFrameRef.current) void applyFrame();
      })
      .catch((err) => {
        if (cancelled) return;
        // Surface mount failures visibly; the render proof must never fail silently.
        console.error("Mol* mount failed:", err);
        target.dataset.mountError = String(err);
      });
    return () => {
      cancelled = true;
      cameraWriteupRef.current?.();
      cameraWriteupRef.current = null;
      viewerWriteupRef.current?.();
      viewerWriteupRef.current = null;
      if (handleRef.current) {
        try {
          handleRef.current.dispose();
        } finally {
          handleRef.current = null;
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suppliedCell]);

  // Reconcile the displayed window and frame to the current props (in place — no re-mount).
  useEffect(() => {
    void applyWindow();
  }, [geometryJson, applyWindow]);
  useEffect(() => {
    void applyFrame();
  }, [frame, applyFrame]);

  // Reconcile the renderer background on a theme change (no re-mount: `setBackground` is a cheap
  // imperative call on the live plugin).
  useEffect(() => {
    handleRef.current?.setBackground(THEME_BG[theme]);
  }, [theme]);
  // Reconcile the bond visual on a `bonds` prop flip.
  useEffect(() => {
    void handleRef.current?.setBonds(Boolean(bonds));
  }, [bonds]);

  return (
    <div
      ref={containerRef}
      // `relative` is load-bearing: Mol* positions its WebGL canvas absolutely, and without a
      // containing block here that canvas anchors to the nearest positioned ancestor (the outer
      // viewport) and would cover the scrubber row above this mount — a mouse user could never
      // reach the Play control (found by the M61-S3 playback journey). Contained here, the canvas
      // fills this box below the scrubber and the controls stay clickable.
      className="relative h-full w-full"
      data-atoms={geometry.species.length}
      // The unit-cell presence signal (M60-S2): `data-has-cell` mirrors the endpoint's *input*
      // answer (whether the canonical geometry carried a cell) — same pattern as `data-atoms`.
      // It is NOT the render proof: the mount separately sets `data-unitcell-drawn` from whether
      // Mol* actually drew a box, and the fidelity e2e asserts that render-level attribute so the
      // P3 no-box invariant is tested against the render, not the input.
      data-has-cell={geometry.cell ? "true" : "false"}
      // The supplied-violet signal (M60-S3, D235): the fabricated cell's wireframe is drawn in
      // the ◆ assumption violet — set from the report-sourced flag, never re-derived here.
      data-cell-supplied={suppliedCell ? "true" : "false"}
      // The bonds-prop signal (a cheap prop-level proof, mirroring `data-has-cell`/`data-cell-
      // supplied` above): NOT the render proof — the mount separately sets `data-bonds-drawn`
      // from whether Mol* actually added the ball-and-stick representation.
      data-bonds={bonds ? "true" : "false"}
    />
  );
}