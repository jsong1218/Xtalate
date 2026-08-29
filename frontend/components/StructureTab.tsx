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
import { StructureViewer } from "@/components/StructureViewer";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import type { GeometryState } from "@/lib/geometry/useGeometry";

const EXPIRED_FILE_COPY =
  "This file's bytes have expired; the reports below remain the complete record.";
const EXPIRED_OUTPUT_COPY =
  "The output bytes have expired; the reports below remain the complete record.";

export interface StructureTabProps {
  /** The geometry query state, fetched by the page through the M59 hook. */
  geometryState: GeometryState;
  /** Optional label shown above the viewport (e.g. the source filename). */
  label?: string;
}

export function StructureTab({ geometryState, label }: StructureTabProps) {
  return (
    <section aria-label="Structure" className="space-y-2">
      <h2 className="text-lg font-semibold text-strong">Structure</h2>
      <StructureTabBody geometryState={geometryState} label={label} />
    </section>
  );
}

function StructureTabBody({ geometryState, label }: StructureTabProps) {
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
  return <StructureViewer geometry={geometry} label={label} />;
}
