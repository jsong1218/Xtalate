"use client";

/**
 * StructureTab (v1.6 M60-S1) — the reusable "Structure" tab/section added to the file and
 * conversion record pages (MASTER_SPEC Part 7 §6; the seam Revision 1.76 reserved for the
 * foundation, Revision 1.77 makes present).
 *
 * It is a **presentation-only** region: the page feeds it the geometry query state from the M59
 * hooks (`useFileGeometry` / `useConversionGeometry`) — the tab never fetches, never re-derives,
 * never recomputes anything (Part 7 §2: the faithful presentation layer). It mounts the M59
 * `StructureViewer` unchanged and renders the honest non-ready states:
 *
 *   - **loading** — the "Loading structure…" affordance (the same wording the viewer's own
 *     dynamic-load placeholder uses).
 *   - **expired** — the geometry endpoint 410s once the underlying bytes are gone (D232:
 *     `FILE_EXPIRED` / `OUTPUT_EXPIRED`); the tab says the bytes are gone and the reports remain
 *     the complete record — reports outlive bytes, exactly like downloads.
 *   - **error** — any other geometry failure renders the service error envelope, never a broken
 *     canvas. A **refused** conversion is handled by the page (it does not mount the tab at all —
 *     the `RefusalPanel` is the substance); here the same rule holds: no geometry, no viewer.
 */
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { LossTag } from "@/components/loss/icons";
import { StructureViewer, type SuppliedCell } from "@/components/StructureViewer";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { exportedFrameAnnotation } from "@/lib/exportedFrame";
import type { GeometryState } from "@/lib/geometry/useGeometry";
import type { GeometrySource } from "@/lib/geometry/useTrajectoryWindow";
import type { ConversionReport } from "@/lib/report/types";

const EXPIRED_FILE_COPY =
  "This file's bytes have expired; the reports below remain the complete record.";
const EXPIRED_OUTPUT_COPY =
  "The output bytes have expired; the reports below remain the complete record.";

export interface StructureTabProps {
  /** The geometry query state, fetched by the page through the M59 hook. */
  geometryState: GeometryState;
  /** Optional label shown above the viewport (e.g. the source filename). */
  label?: string;
  /**
   * The conversion's report (conversion page only, M60-S3 D235). When a rendered quantity's
   * canonical path appears in `conversion_report.supplied`, the viewer marks it violet with its
   * Assumption one click away — the correlation is **report-sourced** (a lookup of `supplied[].path`
   * + `from_assumption`), never re-derived from the geometry. The files page passes nothing, so it
   * never renders violet.
   */
  conversionReport?: ConversionReport;
  /**
   * The read target the Structure tab already renders (M61-S1): the file's own frames, or a
   * conversion's source/output. Passed through to the viewer so a multi-frame object (`frame_count
   * > 1`) gains the scrubber and windows over the same M59 endpoint — additive, never re-derived.
   */
  trajectorySource?: GeometrySource;
}

export function StructureTab({
  geometryState,
  label,
  conversionReport,
  trajectorySource,
}: StructureTabProps) {
  return (
    <section aria-label="Structure" className="space-y-2">
      <h2 className="text-lg font-semibold text-strong">Structure</h2>
      <StructureTabBody
        geometryState={geometryState}
        label={label}
        conversionReport={conversionReport}
        trajectorySource={trajectorySource}
      />
    </section>
  );
}

function StructureTabBody({
  geometryState,
  label,
  conversionReport,
  trajectorySource,
}: StructureTabProps) {
  if (geometryState.status === "loading") {
    return (
      <p role="status" className="text-sm text-muted">
        Loading structure…
      </p>
    );
  }

  if (geometryState.status === "error") {
    const envelope = toErrorEnvelope(
      geometryState.error,
      "GEOMETRY_LOAD_FAILED",
      "Could not load this structure.",
    );
    if (envelope.error.code === "FILE_EXPIRED" || envelope.error.code === "OUTPUT_EXPIRED") {
      return (
        <p className="text-sm text-body">
          {envelope.error.code === "OUTPUT_EXPIRED" ? EXPIRED_OUTPUT_COPY : EXPIRED_FILE_COPY}
        </p>
      );
    }
    return <ErrorEnvelope envelope={envelope} />;
  }

  // `ready` always carries geometry from the hooks; the guard keeps the type honest without
  // re-deriving anything.
  const geometry = geometryState.geometry;
  if (!geometry) return null;

  // The report-sourced exported-frame annotation (S2, D237): on a conversion whose output was
  // produced by a `frame_selection` recovery, name which source frame it is — read only from the
  // Assumption's `parameters.frame_index`, Assumption one click away. Discovery pages (no
  // `conversionReport`) and conversions without a `frame_selection` render nothing.
  const exportedFrame = exportedFrameAnnotation(conversionReport);

  // The supplied-geometry correlation (D235): the fabricated-lattice case. The engine records the
  // fabrication on the `cell` canonical family's leaf paths (`cell.lattice_vectors`, `cell.pbc` —
  // the wire carries no bare `cell` entry), so the check matches the `cell.*` family and is
  // structured so other supplied paths extend cleanly. This is a lookup against the report already
  // on the page — no arithmetic on positions/cell, never re-derived.
  const suppliedCell = conversionReport?.supplied.find(
    (entry) => entry.path === "cell" || entry.path.startsWith("cell."),
  );
  const suppliedAssumption = suppliedCell
    ? conversionReport?.assumptions.find((a) => a.id === suppliedCell.from_assumption)
    : undefined;
  const suppliedCellInfo: SuppliedCell | undefined = suppliedCell
    ? {
        fromAssumption: suppliedCell.from_assumption,
        description: suppliedAssumption?.description,
      }
    : undefined;

  return (
    <>
      {exportedFrame ? (
        <div
          data-testid="exported-frame"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-cb-assumption bg-cb-assumption-bg px-2 py-1.5"
        >
          <LossTag kind="assumption">
            This output is source frame {exportedFrame.index}
          </LossTag>
          <a
            href={`#assumption-${exportedFrame.assumptionId}`}
            className="text-xs font-medium text-cb-assumption underline"
          >
            See Assumption {exportedFrame.assumptionId}
          </a>
        </div>
      ) : null}
      <StructureViewer
        geometry={geometry}
        label={label}
        suppliedCell={suppliedCellInfo}
        trajectorySource={trajectorySource}
      />
    </>
  );
}
