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
import { LossTag } from "@/components/loss/icons";
import { StructureLegend } from "./StructureLegend";

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
 * everywhere it appears — with its Assumption **one click away** (the anchor the Conversion Report
 * panel gives the assumption row). The fact is report-sourced by the caller (`StructureTab` reads
 * `supplied[].path` + `from_assumption`); this component only renders it.
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
}

export function StructureViewer({ geometry, label, suppliedCell }: StructureViewerProps) {
  const [bondsEnabled, setBondsEnabled] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      {label ? (
        <div className="text-xs font-medium text-slate-500">{label}</div>
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
      <div className="relative h-96 w-full overflow-hidden rounded border border-slate-200">
        <MolstarView
          geometry={geometry}
          suppliedCell={Boolean(suppliedCell)}
        />
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
