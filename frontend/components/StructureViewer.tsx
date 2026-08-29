"use client";

/**
 * StructureViewer (v1.6 M59-S2) — the reusable Mol\* mount atom that M60's tab, M61's scrubber,
 * and M62's Compare each consume. Built standalone, not welded to a page.
 *
 * SSR safety: the Mol\* plugin is WebGL/canvas and client-only, so the actual mount lives in a
 * dynamically-imported `ssr: false` chunk (`StructureViewerMolstar`) — the production build never
 * evaluates the plugin on the server (D98).
 *
 * Bonds policy (D234): the loader attaches no bond data and the mount draws an atoms-only
 * representation, so bonds are **off by default**. The toggle only exposes the persistent
 * heuristic badge — bonds are a display inference, never file content, and no report mentions
 * them.
 */
import dynamic from "next/dynamic";
import { useState } from "react";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";

const MolstarView = dynamic(() => import("./StructureViewerMolstar"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-400">
      Loading structure…
    </div>
  ),
});

const BONDS_HEURISTIC_BADGE =
  "Bonds are a display heuristic, not file content";

export interface StructureViewerProps {
  geometry: CanonicalGeometry;
  /** Optional label shown above the viewport (e.g. the source filename). */
  label?: string;
}

export function StructureViewer({ geometry, label }: StructureViewerProps) {
  const [bondsEnabled, setBondsEnabled] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      {label ? (
        <div className="text-xs font-medium text-slate-500">{label}</div>
      ) : null}
      <div className="relative h-96 w-full overflow-hidden rounded border border-slate-200">
        <MolstarView geometry={geometry} />
        {bondsEnabled ? (
          <div
            role="status"
            className="absolute bottom-2 left-2 rounded bg-amber-100 px-2 py-1 text-xs text-amber-900"
          >
            {BONDS_HEURISTIC_BADGE}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        aria-pressed={bondsEnabled}
        onClick={() => setBondsEnabled((v) => !v)}
        className="self-start rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
      >
        {bondsEnabled ? "Hide bonds heuristic" : "Show bonds heuristic"}
      </button>
    </div>
  );
}
