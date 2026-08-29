"use client";

/**
 * The Mol\* mount (v1.6 M59-S2) — the `ssr: false` dynamic chunk behind `StructureViewer`.
 * This module pulls the WebGL plugin and must never be evaluated during server rendering; it is
 * only ever loaded through the viewer's dynamic import.
 */
import { useEffect, useRef } from "react";
import { mountStructureViewer } from "@/lib/geometry/molstarMount";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";

export default function StructureViewerMolstar({
  geometry,
  suppliedCell,
}: {
  geometry: CanonicalGeometry;
  /** When true the unit-cell wireframe is drawn in the supplied-violet (D235). */
  suppliedCell?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const target = containerRef.current;
    if (!target) return;
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void mountStructureViewer(target, geometry, { suppliedCell: Boolean(suppliedCell) })
      .then((dispose) => {
        if (disposed) dispose();
        else {
          cleanup = dispose;
          // The e2e render proof reads these: mounted = the plugin canvas is live,
          // atoms = the declared atom count the loader was fed.
          target.dataset.mounted = "true";
        }
      })
      .catch((err) => {
        // Surface mount failures visibly; the render proof must never fail silently.
        console.error("Mol* mount failed:", err);
        target.dataset.mountError = String(err);
      });
    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [geometry]);

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      data-atoms={geometry.species.length}
      // The unit-cell wireframe signal (M60-S2): the mount draws the box only when the geometry
      // carries a cell — `data-has-cell` mirrors the endpoint's presence answer, so the e2e
      // render proof can assert the box/no-box state honestly (same pattern as `data-atoms`).
      data-has-cell={geometry.cell ? "true" : "false"}
      // The supplied-violet signal (M60-S3, D235): the fabricated cell's wireframe is drawn in
      // the ◆ assumption violet — set from the report-sourced flag, never re-derived here.
      data-cell-supplied={suppliedCell ? "true" : "false"}
    />
  );
}
