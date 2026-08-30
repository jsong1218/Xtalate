"use client";

/**
 * The Mol\\* mount (v1.6 M59-S2, extended M61-S1) — the `ssr: false` dynamic chunk behind
 * `StructureViewer`. This module pulls the WebGL plugin and must never be evaluated during server
 * rendering; it is only ever loaded through the viewer's dynamic import.
 *
 * M61-S1 drives the mount with two pieces: the **window geometry** (the bounded set of decoded
 * frames the scrubber hands over) and the **absolute** report index to display. A window *change*
 * re-mounts (fresh trajectory over the new frame set); a frame *change within* the window calls the
 * mount's cheap `setFrame` (the `ModelFromTrajectory` `modelIndex` update — no rebuild), which also
 * redraws that frame's unit-cell wireframe (variable-cell trajectories breathe; a cell-less frame
 * draws no box — `data-unitcell-drawn` stays honest per displayed frame).
 */
import { useEffect, useRef } from "react";
import {
  mountStructureViewer,
  type MountedStructureViewer,
} from "@/lib/geometry/molstarMount";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";

export default function StructureViewerMolstar({
  geometry,
  frameIndex,
  suppliedCell,
}: {
  geometry: CanonicalGeometry;
  /** The absolute report index to display (defaults to the geometry's frame_index_base). */
  frameIndex?: number;
  /** When true the unit-cell wireframe is drawn in the supplied-violet (D235). */
  suppliedCell?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<MountedStructureViewer | null>(null);
  // The window identity this handle was mounted for, and the frame the mount already shows.
  const mountedGeoRef = useRef<string | null>(null);
  const mountedFrameRef = useRef<number | null>(null);

  const geometryJson = JSON.stringify(geometry);
  const geometryJsonRef = useRef(geometryJson);
  geometryJsonRef.current = geometryJson;

  const frame = frameIndex ?? geometry.frame_index_base ?? 0;

  // (Re)mount whenever the display geometry (window) changes — a window change is a trajectory
  // rebuild over the new frame set. Within a window this effect does not re-run, so the second
  // effect below handles frame-only changes cheaply.
  useEffect(() => {
    const target = containerRef.current;
    if (!target) return;
    let cancelled = false;
    // Tear down any prior window's mount (dispose is idempotent).
    if (handleRef.current) {
      try {
        handleRef.current.dispose();
      } finally {
        handleRef.current = null;
      }
    }
    mountedGeoRef.current = null;
    target.dataset.mounted = "false";
    target.dataset.currentFrame = String(frame);

    void mountStructureViewer(target, geometry, {
      suppliedCell: Boolean(suppliedCell),
      initialFrameIndex: frame,
    })
      .then((handle) => {
        if (cancelled) {
          handle.dispose();
          return;
        }
        handleRef.current = handle;
        mountedGeoRef.current = JSON.stringify(geometry);
        mountedFrameRef.current = frame;
        target.dataset.mounted = "true";
      })
      .catch((err) => {
        if (cancelled) return;
        // Surface mount failures visibly; the render proof must never fail silently.
        console.error("Mol* mount failed:", err);
        target.dataset.mountError = String(err);
      });
    return () => {
      cancelled = true;
      // Unmount / next window-change: dispose the mounted handle (includes component unmount).
      if (handleRef.current) {
        try {
          handleRef.current.dispose();
        } finally {
          handleRef.current = null;
        }
      }
    };
    // Re-mount only on a window change (geometry identity) or the bonds-scheme toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry, suppliedCell]);

  // A frame-only change within the mounted window: cheap in-place frame set (no rebuild).
  useEffect(() => {
    const handle = handleRef.current;
    if (!handle) return;
    // Only drive frames that live in the mounted window (a boundary scrub re-mounts via the effect
    // above once the new window arrives; until then the previous window holds the edge frame).
    if (mountedGeoRef.current === null || mountedGeoRef.current !== geometryJsonRef.current) return;
    if (mountedFrameRef.current === frame) return;
    mountedFrameRef.current = frame;
    void handle.setFrame(frame).catch((err) => {
      console.error("Mol* setFrame failed:", err);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame]);

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
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
    />
  );
}