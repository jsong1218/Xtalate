/**
 * StructureViewerMolstar lifecycle tests (v1.6 M61 review #2): the plugin is mounted **once**, and
 * a window change swaps the frame set **in place** via the handle's `setWindow` — it does not
 * dispose and re-mount the plugin (which would flash the canvas and reset the camera every window
 * boundary during playback). A frame change within the window calls the cheap `setFrame`.
 *
 * `mountStructureViewer` is mocked to a fake handle that records the imperative calls, so these
 * tests assert the mount lifecycle without a real WebGL context. The per-frame render fidelity
 * (`data-unitcell-drawn` etc.) is covered against real Mol* in the e2e.
 */
import { render, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { Schemas } from "@/lib/api/client";
import StructureViewerMolstar from "./StructureViewerMolstar";

const { mountMock, setFrame, setWindow, dispose, setBackground, setBonds, resetCamera } =
  vi.hoisted(() => ({
    mountMock: vi.fn(),
    setFrame: vi.fn(async () => {}),
    setWindow: vi.fn(async () => {}),
    dispose: vi.fn(),
    setBackground: vi.fn(),
    setBonds: vi.fn(async () => {}),
    resetCamera: vi.fn(),
  }));

vi.mock("@/lib/geometry/molstarMount", () => ({
  mountStructureViewer: mountMock,
}));

/** A window of `n` frames starting at absolute `base`. */
function windowFixture(base: number, n: number): Schemas["GeometryResponse"] {
  return {
    source: { format_id: "extxyz", filename: "relax.extxyz" },
    species: ["C", "H"],
    cell: null,
    frame_index_base: base,
    frame_count: 16,
    frames: Array.from({ length: n }, (_, i) => ({
      index: base + i,
      positions: [
        [base + i, 0, 0],
        [base + i + 1.1, 0, 0],
      ],
      cell: null,
    })),
  };
}

/** Flush the mount promise + the post-mount reconcile microtasks. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  mountMock.mockReset();
  setFrame.mockClear();
  setWindow.mockClear();
  dispose.mockClear();
  setBackground.mockClear();
  setBonds.mockClear();
  resetCamera.mockClear();
  mountMock.mockResolvedValue({ setFrame, setWindow, dispose, setBackground, setBonds, resetCamera });
});

describe("StructureViewerMolstar lifecycle", () => {
  it("mounts the plugin once and swaps windows in place (setWindow, no re-mount)", async () => {
    const first = windowFixture(0, 8);
    const { rerender } = render(<StructureViewerMolstar geometry={first} frameIndex={0} />);
    await settle();
    expect(mountMock).toHaveBeenCalledTimes(1);

    // A window change: new frame set, next frame.
    const second = windowFixture(8, 8);
    rerender(<StructureViewerMolstar geometry={second} frameIndex={8} />);
    await settle();

    // The plugin was NOT re-mounted or disposed — the window was swapped in place.
    expect(mountMock).toHaveBeenCalledTimes(1);
    expect(dispose).not.toHaveBeenCalled();
    expect(setWindow).toHaveBeenCalledTimes(1);
    expect(setWindow).toHaveBeenCalledWith(second, 8);
  });

  it("drives a frame-only change within the window through the cheap setFrame", async () => {
    const win = windowFixture(0, 8);
    const { rerender } = render(<StructureViewerMolstar geometry={win} frameIndex={0} />);
    await settle();

    rerender(<StructureViewerMolstar geometry={win} frameIndex={3} />);
    await settle();

    expect(setWindow).not.toHaveBeenCalled();
    expect(setFrame).toHaveBeenCalledWith(3);
    expect(mountMock).toHaveBeenCalledTimes(1);
  });

  it("re-mounts only when the supplied-cell color changes (fixed at mount)", async () => {
    const win = windowFixture(0, 8);
    const { rerender } = render(
      <StructureViewerMolstar geometry={win} frameIndex={0} suppliedCell={false} />,
    );
    await settle();
    expect(mountMock).toHaveBeenCalledTimes(1);

    rerender(<StructureViewerMolstar geometry={win} frameIndex={0} suppliedCell={true} />);
    await settle();
    // The unit-cell color is fixed at mount, so a suppliedCell change re-mounts (disposes first).
    expect(dispose).toHaveBeenCalled();
    expect(mountMock).toHaveBeenCalledTimes(2);
  });

  it("passes a theme-aware background to the mount and updates it when theme changes", async () => {
    document.documentElement.setAttribute("data-theme", "dark");
    const win = windowFixture(0, 8);
    render(<StructureViewerMolstar geometry={win} frameIndex={0} />);
    await settle();
    expect(mountMock).toHaveBeenCalledWith(
      expect.anything(),
      win,
      expect.objectContaining({ backgroundColor: 0x0f172a }),
    );
    document.documentElement.removeAttribute("data-theme");
  });

  it("calls setBonds when the bonds prop flips", async () => {
    const win = windowFixture(0, 8);
    const { rerender } = render(
      <StructureViewerMolstar geometry={win} frameIndex={0} bonds={false} />,
    );
    await settle();
    setBonds.mockClear();
    rerender(<StructureViewerMolstar geometry={win} frameIndex={0} bonds={true} />);
    await settle();
    expect(setBonds).toHaveBeenCalledWith(true);
  });

  it("hands resetCamera upward through the viewerControls seam", async () => {
    const win = windowFixture(0, 8);
    const onReady = vi.fn(() => () => {});
    render(<StructureViewerMolstar geometry={win} frameIndex={0} viewerControls={{ onReady }} />);
    await settle();
    expect(onReady).toHaveBeenCalledWith(
      expect.objectContaining({ resetCamera: expect.any(Function) }),
    );
  });
});
