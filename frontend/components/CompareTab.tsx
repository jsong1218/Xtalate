"use client";

/**
 * CompareTab (v1.6 M62-S1, D239) — the mission-payoff tab: the two structures the Validation
 * Engine already diffed, shown to the eyes **side by side**, so *seeing* and *reading the report*
 * examine identical evidence (MASTER_SPEC Part 7 §6). It composes **two** of the existing M59
 * `StructureViewer` atoms for the conversion's **source** and **re-parsed output** Canonical
 * Objects (`side=source` / `side=output`, D232), both fed the canonical geometry JSON directly
 * through the M59 loader (D233) — **never a hidden export** to a display format, and never a
 * client-side diff (that is S2's report-sourced annotations and the no-recompute boundary).
 *
 * S1 ships the tab + the two synchronized viewers:
 *
 *  - **Camera-locked always.** A guarded broadcast between the two mounts: rotate/zoom one and the
 *    other follows. Each viewer exposes its camera through the M62 camera seam
 *    (`handle.camera` → get/set/observe); this tab wires A's change to B's `setSnapshot` and
 *    vice-versa, re-entrancy-guarded (an "applying a remote camera" flag) so the broadcast never
 *    ping-pongs.
 *  - **Frame-locked only where a correspondence honestly exists.** When source and output have the
 *    **same `frame_count`**, **one** scrubber drives **both** (the Compare tab owns the index and
 *    hands it to each viewer via `frameControl`). When the output is a **single selected frame**
 *    (`frame_selection`), the **source** scrubs, the output holds its one frame, and the source
 *    track carries the **exported-frame marker** at the report's resolved `parameters.frame_index`
 *    (D237, placed here; read with `exportedFrameAnnotation`, **no client arithmetic**). The two
 *    objects never pretend frame-N-of-source equals frame-N-of-output when the counts differ —
 *    that would be an invented correspondence the report never asserted.
 *
 * This tab is a *presentation* of the two objects the validator already diffed — nothing it shows is
 * knowable only from this tab. Honest non-ready states (loading / expired bytes / service error) are
 * inherited from the M60 Structure tab; S3 hardens the partial-expiry cases. **Frontend-only**:
 * `side=source` shipped in M59, and D239/Rev 1.82 record this slice.
 */
import { useCallback, useRef, useState } from "react";
import { ErrorEnvelope } from "@/components/ErrorEnvelope";
import { StructureViewer } from "@/components/StructureViewer";
import { TrajectoryScrubber } from "@/components/TrajectoryScrubber";
import { toErrorEnvelope } from "@/lib/api/useInspection";
import { exportedFrameAnnotation } from "@/lib/exportedFrame";
import { useConversionGeometry, type GeometryState } from "@/lib/geometry/useGeometry";
import type { StructureViewerCamera } from "@/lib/geometry/molstarMount";
import type { ConversionReport, ValidationReport } from "@/lib/report/types";

/** The M60 honest-state copy, reused verbatim (reports outlive bytes, exactly like downloads). */
const EXPIRED_FILE_COPY =
  "This file's bytes have expired; the reports below remain the complete record.";
const EXPIRED_OUTPUT_COPY =
  "The output bytes have expired; the reports below remain the complete record.";

/**
 * The camera-lock broadcast (M62-S1, D239), held for one tab: when a viewer's camera changes
 * (a user orbit-control drag on that side), its snapshot is pushed onto the sibling viewer. Each
 * side's `onChange` handler checks an "applying a remote camera" flag for **the same side** before
 * rebroadcasting: while this tab is pushing source→output, the output viewer emits its own
 * `changed` event (the echo), whose handler sees `output` applying and stops — no ping-pong loop.
 */
function useCameraLock(): {
  onSourceReady: (cam: StructureViewerCamera) => () => void;
  onOutputReady: (cam: StructureViewerCamera) => () => void;
} {
  const sourceRef = useRef<StructureViewerCamera | null>(null);
  const outputRef = useRef<StructureViewerCamera | null>(null);
  const applyingRef = useRef({ source: false, output: false });

  const onSourceReady = useCallback((cam: StructureViewerCamera) => {
    sourceRef.current = cam;
    const unsub = cam.onChange(() => {
      if (applyingRef.current.source) return; // a remote echo, not a user gesture — stop
      const other = outputRef.current;
      if (!other) return;
      applyingRef.current.output = true;
      try {
        other.setSnapshot(cam.getSnapshot());
      } finally {
        applyingRef.current.output = false;
      }
    });
    return unsub;
  }, []);

  const onOutputReady = useCallback((cam: StructureViewerCamera) => {
    outputRef.current = cam;
    const unsub = cam.onChange(() => {
      if (applyingRef.current.output) return; // a remote echo, not a user gesture — stop
      const other = sourceRef.current;
      if (!other) return;
      applyingRef.current.source = true;
      try {
        other.setSnapshot(cam.getSnapshot());
      } finally {
        applyingRef.current.source = false;
      }
    });
    return unsub;
  }, []);

  return { onSourceReady, onOutputReady };
}

export interface CompareTabProps {
  conversionId: string;
  /** The conversion's report (`removed`/`supplied`/`assumptions`), already on the page. */
  conversionReport?: ConversionReport;
  /** The validation report, already on the page (S2 reads its `checks[].measured`). */
  validationReport?: ValidationReport;
}

/**
 * The honest non-ready state for the whole tab (S3 hardens the partial-expiry case): if either side
 * is an error, render the service envelope (or the M60 expired copy when the bytes are gone — the
 * reports remain the substance); if either side is still loading, render the loading affordance.
 * Neither side carved into a half-rendered canvas.
 */
function ComparePrecondition({
  source,
  output,
}: {
  source: GeometryState;
  output: GeometryState;
}) {
  const errored = source.status === "error" ? source : output.status === "error" ? output : null;
  if (errored) {
    const envelope = toErrorEnvelope(
      errored.error,
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
  if (source.status !== "ready" || output.status !== "ready") {
    return (
      <p role="status" className="text-sm text-muted">
        Loading structure…
      </p>
    );
  }
  return null;
}

export function CompareTab({ conversionId, conversionReport }: CompareTabProps) {
  const sourceGeometry = useConversionGeometry(conversionId, "source");
  const outputGeometry = useConversionGeometry(conversionId, "output");
  const { onSourceReady, onOutputReady } = useCameraLock();
  // The Compare tab owns the shared scrubber index; each viewer renders it via `frameControl`.
  const [frame, setFrame] = useState(0);

  const precondition = ComparePrecondition({
    source: sourceGeometry,
    output: outputGeometry,
  });
  if (precondition !== null) {
    return (
      <section aria-label="Compare" className="space-y-2">
        <h2 className="text-lg font-semibold text-strong">Compare</h2>
        {precondition}
      </section>
    );
  }

  // Both sides ready — the honest frame-lock decision is now well-defined (S1; no invented
  // correspondence when the counts differ and there is no frame_selection).
  const sourceGeo = sourceGeometry.geometry!;
  const outputGeo = outputGeometry.geometry!;
  const srcCount = sourceGeo.frame_count;
  const outCount = outputGeo.frame_count;
  const countsMatch = srcCount === outCount;
  const sourceIsTrajectory = srcCount > 1;
  // The report-sourced exported-frame marker (D237 placed here): which source frame a
  // `frame_selection` output is — literally `parameters.frame_index`, no client arithmetic.
  const exportedFrame = exportedFrameAnnotation(conversionReport);

  // The source always scrubs when it is a trajectory. The output is lock-followed only where the
  // frame counts match (the honest correspondence); a single-frame `frame_selection` output holds
  // its one frame while the source scrubs toward the marker.
  const sourceFrameControl = sourceIsTrajectory ? { frame } : undefined;
  const outputFrameControl = countsMatch ? { frame } : undefined;

  return (
    <section aria-label="Compare" className="space-y-2">
      <h2 className="text-lg font-semibold text-strong">Compare</h2>
      {sourceIsTrajectory ? (
        <TrajectoryScrubber
          frameCount={srcCount}
          frameIndexBase={sourceGeo.frame_index_base ?? 0}
          frame={frame}
          onScrub={setFrame}
          markerFrame={exportedFrame?.index}
        />
      ) : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <StructureViewer
          geometry={sourceGeo}
          label="Source"
          trajectorySource={{ kind: "conversion", conversionId, side: "source" }}
          cameraControls={{ onReady: onSourceReady }}
          frameControl={sourceFrameControl}
        />
        <StructureViewer
          geometry={outputGeo}
          label="Output"
          trajectorySource={{ kind: "conversion", conversionId, side: "output" }}
          cameraControls={{ onReady: onOutputReady }}
          frameControl={outputFrameControl}
        />
      </div>
    </section>
  );
}