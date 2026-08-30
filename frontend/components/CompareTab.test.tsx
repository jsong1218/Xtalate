/**
 * CompareTab tests (v1.6 M62-S1, D239). `StructureViewer` (and the Mol* chunk behind it) is mocked
 * to a capture stub so the tests exercise CompareTab's own logic — the two synchronized viewer
 * wiring, the camera-lock broadcast with its re-entrancy guard, the honest frame-lock (one shared
 * scrubber), and the report-sourced exported-frame marker (real `exportedFrameAnnotation` + real
 * `TrajectoryScrubber`, never a computed frame).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/lib/api/client";
import type { ConversionReport, ValidationReport } from "@/lib/report/types";
import type { StructureViewerCamera } from "@/lib/geometry/molstarMount";
import { CompareTab } from "./CompareTab";
import type { CameraControls } from "./StructureViewerMolstar";

/** A fake Mol* camera seam for one viewer (recorded setSnapshot, subscribable onChange). */
const FakeCam = vi.hoisted(() => {
  return class FakeCam {
    snapshot: Record<string, number> = { p: 0 };
    listeners: Array<() => void> = [];
    setSnapshotCalls: Array<Record<string, number>> = [];
    setSnapshot(s: Record<string, number>) {
      this.setSnapshotCalls.push(s);
      this.snapshot = s;
      this.listeners.forEach((l) => l());
    }
    getSnapshot() {
      return { ...this.snapshot };
    }
    onChange(l: () => void) {
      this.listeners.push(l);
      return () => {
        this.listeners = this.listeners.filter((x) => x !== l);
      };
    }
    /** Simulate a user orbit-control drag: mutate then fire the change observable. */
    userDrag(s: Record<string, number>) {
      this.snapshot = s;
      this.listeners.forEach((l) => l());
    }
  };
});

const store = vi.hoisted(() => {
  const viewerCalls: Array<{
    label: string;
    frameControl?: { frame: number };
    cameraControls?: CameraControls;
    suppliedCell?: { fromAssumption: string; description?: string };
  }> = [];
  return { viewerCalls };
});

vi.mock("@/components/StructureViewer", () => ({
  StructureViewer: (props: {
    label: string;
    frameControl?: { frame: number };
    cameraControls?: unknown;
    suppliedCell?: { fromAssumption: string; description?: string };
  }) => {
    store.viewerCalls.push({
      label: props.label,
      frameControl: props.frameControl,
      cameraControls: props.cameraControls as unknown as CameraControls,
      suppliedCell: props.suppliedCell,
    });
    return (
      <div data-testid={`viewer-${props.label}`} data-frame={props.frameControl?.frame ?? 0}>
        {props.label}
      </div>
    );
  },
}));

const geometryHook = vi.hoisted(() => vi.fn());
vi.mock("@/lib/geometry/useGeometry", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/geometry/useGeometry")>();
  return { ...actual, useConversionGeometry: geometryHook };
});

function geometryFixture(frameCount: number): Schemas["GeometryResponse"] {
  return {
    source: { format_id: "extxyz", filename: "relax.extxyz" },
    species: ["C", "H"],
    cell: null,
    frame_index_base: 0,
    frame_count: frameCount,
    frames: [
      {
        index: 0,
        positions: [
          [0, 0, 0],
          [0.1, 0, 0],
        ],
        cell: null,
      },
    ],
  };
}

function reportWithSelection(frameIndex: number): ConversionReport {
  return {
    report_id: "r1",
    stage: "final",
    status: "completed",
    mode: "permissive",
    created_at: "2026-01-01T00:00:00Z",
    source: { format_id: "extxyz", filename: "relax.traj" },
    target: { format_id: "poscar", filename: "POSCAR" },
    preserved: [],
    removed: [],
    supplied: [],
    assumptions: [
      {
        id: "A1",
        scenario: "frame_selection",
        choice: "index",
        parameters: { frame_index: frameIndex },
        origin: "user",
        description: "Selected source frame.",
      },
    ],
    warnings: [],
    refusal: null,
  };
}

function emptyReport(): ConversionReport {
  return {
    report_id: "r1",
    stage: "final",
    status: "completed",
    mode: "permissive",
    created_at: "2026-01-01T00:00:00Z",
    source: { format_id: "extxyz", filename: "relax.traj" },
    target: { format_id: "poscar", filename: "POSCAR" },
    preserved: [],
    removed: [],
    supplied: [],
    assumptions: [],
    warnings: [],
    refusal: null,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  store.viewerCalls.length = 0;
});

function renderReady(
  sourceCount: number,
  outputCount: number,
  conversionReport?: ConversionReport,
  validationReport?: ValidationReport,
) {
  geometryHook.mockImplementation((_id: string, side: "source" | "output") =>
    side === "source"
      ? { status: "ready", geometry: geometryFixture(sourceCount) }
      : { status: "ready", geometry: geometryFixture(outputCount) },
  );
  return render(
    <CompareTab
      conversionId="cnv-1"
      conversionReport={conversionReport ?? emptyReport()}
      validationReport={validationReport}
    />,
  );
}

/** A Validation Report whose `positions_rmsd` check carries the given `rmsd_ang` measurement. */
function validationWith(
  rmsdAng: number,
  status: "pass" | "warn" | "fail" | "skipped" = "pass",
): ValidationReport {
  return {
    report_id: "v1",
    conversion_report_id: "r1",
    created_at: "2026-01-01T00:00:00Z",
    status: status === "fail" ? "failed" : status === "warn" ? "passed_with_warnings" : "passed",
    checks: [
      {
        check_id: "positions_rmsd",
        status,
        paths: ["atoms.positions"],
        measured: { rmsd_ang: rmsdAng, frames_compared: 1 },
        tolerance_applied: null,
        message: "positions equal within tolerance",
        skip_reason: status === "skipped" ? "frames not comparable across formats" : null,
      },
    ],
    tolerance_profile: { name: "default" },
    reparse_issues: [],
    schema_version: "1.0.0",
  };
}

function viewer(label: "Source" | "Output") {
  const call = store.viewerCalls.find((c) => c.label === label);
  return call;
}

describe("CompareTab — two synchronized viewers", () => {
  it("mounts source and output viewers fed from their own sides", () => {
    renderReady(1, 1);
    expect(screen.getByTestId("viewer-Source")).toBeInTheDocument();
    expect(screen.getByTestId("viewer-Output")).toBeInTheDocument();
    expect(geometryHook).toHaveBeenCalledWith("cnv-1", "source");
    expect(geometryHook).toHaveBeenCalledWith("cnv-1", "output");
  });

  it("locks the cameras: a source drag pushes to output, and the echo does not ping-pong", () => {
    renderReady(1, 1);
    const src = new FakeCam();
    const out = new FakeCam();
    // Hand each viewer's camera upward, exactly as the real mount does once mounted. The fake
    // camera is structurally loose; it is only used through the onReady seam, so it is erased to
    // the seam's own type.
    act(() => {
      viewer("Source")!
        .cameraControls!.onReady(src as unknown as StructureViewerCamera);
      viewer("Output")!.cameraControls!.onReady(out as unknown as StructureViewerCamera);
    });

    // A user drags the source viewer → the output should follow.
    act(() => src.userDrag({ p: 5 }));
    expect(out.setSnapshotCalls).toEqual([{ p: 5 }]);
    // The follow applies output→... no: the echo of the output's own setSnapshot must NOT push back
    // onto the source. `userDrag` on source is one gesture; source is never re-set by its own echo.
    expect(src.setSnapshotCalls).toEqual([]);

    // And the reverse: a user drag on the output pushes to source, its echo guarded.
    act(() => out.userDrag({ p: 7 }));
    // output.setSnapshot called again? No: that was a source→output push, already counted. The
    // fresh output gesture pushes source→output, not output→source.
    expect(src.setSnapshotCalls).toEqual([{ p: 7 }]);
    // No echo loop: the pushed source change did not re-push output.
    expect(out.setSnapshotCalls).toEqual([{ p: 5 }]);
  });

  it("drives both viewers with one scrubber when the frame counts match", () => {
    renderReady(4, 4);
    const slider = screen.getByLabelText("Trajectory frame");
    expect(slider).toBeInTheDocument();
    // One shared scrubber: both sides receive the same controlled frame as it advances.
    fireEvent.change(slider, { target: { value: "3" } });
    expect(screen.getByTestId("viewer-Source")).toHaveAttribute("data-frame", "3");
    expect(screen.getByTestId("viewer-Output")).toHaveAttribute("data-frame", "3");
  });

  it("for a frame_selection output the source scrubs alone and the output holds its one frame", () => {
    renderReady(4, 1, reportWithSelection(2));
    const slider = screen.getByLabelText("Trajectory frame");
    fireEvent.change(slider, { target: { value: "3" } });
    expect(screen.getByTestId("viewer-Source")).toHaveAttribute("data-frame", "3");
    expect(screen.getByTestId("viewer-Output")).toHaveAttribute("data-frame", "0");
  });

  it("places the exported-frame marker from the report's own frame_index, verbatim", () => {
    // `parameters.frame_index: 999` marks 999 even against a mismatched-looking frame_count — the
    // marker is the report's integer, never a computed `last → frame_count - 1`.
    renderReady(4, 1, reportWithSelection(999));
    expect(screen.getByTestId("exported-frame-marker")).toHaveTextContent("Exported frame 999");
  });

  it("shows no marker when there is no frame_selection Assumption", () => {
    renderReady(4, 1, emptyReport());
    expect(screen.queryByTestId("exported-frame-marker")).not.toBeInTheDocument();
  });

  it("renders no scrubber when neither side is a trajectory (both single-frame)", () => {
    renderReady(1, 1);
    expect(screen.queryByLabelText("Trajectory frame")).not.toBeInTheDocument();
    expect(screen.getByTestId("viewer-Source")).toHaveAttribute("data-frame", "0");
    expect(screen.getByTestId("viewer-Output")).toHaveAttribute("data-frame", "0");
  });
});

describe("CompareTab — report-sourced difference annotations (M62-S2, D240)", () => {
  it("shows the ValidationReport's own positions_rmsd measured value — read, never computed", () => {
    renderReady(1, 1, emptyReport(), validationWith(3.2e-13));
    const overlay = screen.getByTestId("rmsd-overlay");
    expect(overlay).toHaveTextContent("3.2e-13");
    // The check row is one click away, on the ValidationReportPanel's per-check anchor.
    const link = screen.getByRole("link", { name: /see the check row/i });
    expect(link).toHaveAttribute("href", "#check-positions_rmsd");
  });

  it("shows a different report value, proving it is read and not computed", () => {
    renderReady(1, 1, emptyReport(), validationWith(0.0184));
    const overlay = screen.getByTestId("rmsd-overlay");
    expect(overlay).toHaveTextContent("0.0184");
    expect(overlay).not.toHaveTextContent("3.2e-13");
  });

  it("renders a skipped positions_rmsd honestly, with no number and no overlay", () => {
    renderReady(1, 1, emptyReport(), validationWith(0, "skipped"));
    expect(screen.queryByTestId("rmsd-overlay")).not.toBeInTheDocument();
  });

  it("renders no RMSD overlay when the validation report is absent", () => {
    renderReady(1, 1);
    expect(screen.queryByTestId("rmsd-overlay")).not.toBeInTheDocument();
  });

  it("lists the dropped fields with verbatim reasons on the source side", () => {
    const reportWithRemoved: ConversionReport = {
      ...emptyReport(),
      removed: [
        {
          path: "dynamics.velocities",
          reason: "XYZ cannot hold velocities — they were not written.",
          detail: null,
        },
      ],
    };
    renderReady(1, 1, reportWithRemoved, validationWith(0));
    const row = screen.getByTestId("removed-dynamics.velocities");
    expect(row).toHaveTextContent("dynamics.velocities");
    // The report's own words, never a paraphrase.
    expect(row).toHaveTextContent("XYZ cannot hold velocities — they were not written.");
  });

  it("marks a supplied lattice violet on the output side only (the M60 D235 rule doing its comparison job)", () => {
    const reportWithSupplied: ConversionReport = {
      ...emptyReport(),
      supplied: [{ path: "cell.lattice_vectors", from_assumption: "A2", detail: null }],
      assumptions: [
        {
          id: "A2",
          scenario: "missing_lattice",
          choice: "bounding_box",
          parameters: {},
          origin: "user",
          description: "Bounding-box lattice for the selected frame.",
        },
      ],
    };
    renderReady(1, 1, reportWithSupplied, validationWith(0));
    expect(viewer("Output")!.suppliedCell?.fromAssumption).toBe("A2");
    // The source side conspicuously lacks the fabricated lattice.
    expect(viewer("Source")!.suppliedCell).toBeUndefined();
  });

  it("shows neither overlay nor dropped list on a conversion with no removed/supplied/rmsd", () => {
    renderReady(1, 1);
    expect(screen.queryByTestId("rmsd-overlay")).not.toBeInTheDocument();
    expect(screen.queryByText(/fields the target could not hold/i)).not.toBeInTheDocument();
    expect(viewer("Output")!.suppliedCell).toBeUndefined();
  });
});

describe("CompareTab — honest non-ready states, no analysis surface (M62-S3, Rev 1.84)", () => {
  /** An expired-side geometry error, shaped as the endpoint's 410 envelope (D232). */
  function expiredError(side: "source" | "output") {
    return {
      status: "error" as const,
      error: {
        error: {
          code: side === "source" ? "FILE_EXPIRED" : "OUTPUT_EXPIRED",
          message: "The bytes are gone.",
        },
      },
    };
  }

  function renderStates(source: unknown, output: unknown) {
    geometryHook.mockImplementation((_id: string, side: "source" | "output") =>
      side === "source" ? source : output,
    );
    return render(
      <CompareTab conversionId="cnv-1" conversionReport={emptyReport()} validationReport={undefined} />,
    );
  }

  it("an expired output renders the M60 honest expired state — no viewer, no half canvas", () => {
    renderStates({ status: "ready", geometry: geometryFixture(1) }, expiredError("output"));
    expect(
      screen.getByText(/The output bytes have expired; the reports below remain the complete record\./),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Source")).not.toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Output")).not.toBeInTheDocument();
  });

  it("a one-side-expired compare names the expired side — never a silent one-sided comparison", () => {
    // The source side persists, but the output's bytes are gone: the honest partial state names the
    // output and renders NO viewer — the surviving source is never silently shown alone as whole.
    renderStates({ status: "ready", geometry: geometryFixture(1) }, expiredError("output"));
    expect(screen.getByText(/The output bytes have expired/)).toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Source")).not.toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Output")).not.toBeInTheDocument();

    // And the mirror: the source side expired while the output persists.
    renderStates(expiredError("source"), { status: "ready", geometry: geometryFixture(1) });
    expect(screen.getByText(/This file's bytes have expired; the reports below remain the complete record\./)).toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Source")).not.toBeInTheDocument();
  });

  it("when both sides' bytes are gone, both expired copies read", () => {
    renderStates(expiredError("source"), expiredError("output"));
    expect(screen.getByText(/This file's bytes have expired/)).toBeInTheDocument();
    expect(screen.getByText(/The output bytes have expired/)).toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Output")).not.toBeInTheDocument();
  });

  it("a non-expiry geometry failure renders the service envelope, not a canvas", () => {
    renderStates(
      { status: "ready", geometry: geometryFixture(1) },
      { status: "error", error: { error: { code: "SERVICE_DOWN", message: "backend unreachable" } } },
    );
    expect(screen.getByText("backend unreachable")).toBeInTheDocument();
    expect(screen.getByText("SERVICE_DOWN")).toBeInTheDocument();
    expect(screen.queryByTestId("viewer-Output")).not.toBeInTheDocument();
  });

  it("holds the loading affordance until BOTH sides are ready", () => {
    renderStates({ status: "ready", geometry: geometryFixture(1) }, { status: "loading" });
    expect(screen.getByRole("status")).toHaveTextContent("Loading structure…");
    expect(screen.queryByTestId("viewer-Source")).not.toBeInTheDocument();
  });

  it("no analysis surface: the only numbers/artifacts on the tab come from the reports, never per-atom", () => {
    // The no-heat-map / no-per-atom-recompute line (Rev 1.84): with empty reports and single-frame
    // objects, the Compare section renders exactly the two viewers and nothing else — no computed
    // difference overlay, no per-atom artifact, no analysis of its own.
    renderReady(1, 1, emptyReport());
    const section = screen.getByRole("region", { name: "Compare" });
    const artifactIds = [
      "rmsd-overlay",
      "exported-frame-marker",
      "removed-dynamics.velocities",
    ];
    for (const id of artifactIds) {
      expect(section.querySelector(`[data-testid="${id}"]`)).toBeNull();
    }
    // The section's only rendered structure surfaces are the two side-by-side viewers.
    expect(section.querySelectorAll("[data-testid^='viewer-']")).toHaveLength(2);
  });
});