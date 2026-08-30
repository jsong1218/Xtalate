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
import type { ConversionReport } from "@/lib/report/types";
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
  }> = [];
  return { viewerCalls };
});

vi.mock("@/components/StructureViewer", () => ({
  StructureViewer: (props: {
    label: string;
    frameControl?: { frame: number };
    cameraControls?: unknown;
  }) => {
    store.viewerCalls.push({
      label: props.label,
      frameControl: props.frameControl,
      cameraControls: props.cameraControls as unknown as CameraControls,
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

function renderReady(sourceCount: number, outputCount: number, conversionReport?: ConversionReport) {
  geometryHook.mockImplementation((_id: string, side: "source" | "output") =>
    side === "source"
      ? { status: "ready", geometry: geometryFixture(sourceCount) }
      : { status: "ready", geometry: geometryFixture(outputCount) },
  );
  return render(
    <CompareTab
      conversionId="cnv-1"
      conversionReport={conversionReport ?? emptyReport()}
    />,
  );
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