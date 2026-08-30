/**
 * useTrajectoryWindow tests (v1.6 M61-S1, D236): the client-side sliding window keeps a **bounded**
 * set of decoded frames (never the whole trajectory — the memory invariant, unit-tested with a fake
 * fetch) and drops the old window when a new one loads. The ranged geometry endpoint is stubbed by
 * mocking `@/lib/api/client` (Mol* is WebGL and irrelevant here).
 *
 * A real render harness drives the hook through `fireEvent` + `waitFor` (the act-safe path the rest
 * of the suite uses — `renderHook` + manual `act` does not flush async adoptions in this setup), and
 * exposes the hook's readout in the DOM so tests assert what the user sees.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import type { Schemas } from "@/lib/api/client";
import {
  MAX_WINDOWS,
  useTrajectoryWindow,
  WINDOW_SIZE,
  type GeometrySource,
} from "./useTrajectoryWindow";

type GeometryResponse = Schemas["GeometryResponse"];

/** The fake client's GET: slices a generated `total`-frame geometry by the `frames=start:end` param. */
const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));

vi.mock("@/lib/api/client", () => ({
  apiClient: { GET: getMock },
}));

/** A single-atom trajectory piece: `[start, start+len)` frames with index == absolute position. */
function windowGeometry(total: number, start: number, end: number): GeometryResponse {
  const frames = [];
  for (let i = start; i < end; i++) {
    frames.push({ index: i, positions: [[i, 0, 0]], cell: null });
  }
  return {
    source: { format_id: "extxyz", filename: "traj.extxyz" },
    species: ["C"],
    cell: null,
    frame_index_base: start,
    frame_count: total,
    frames,
  };
}

/** Answer the geometry endpoint for a `/v1/files/{id}/geometry` range request. */
function mockRangedFile(total: number) {
  getMock.mockImplementation(
    async (_url: string, { params }: { params: { query: { frames: string } } }) => {
      const [s, e] = params.query.frames.split(":").map(Number);
      return { data: windowGeometry(total, s, e), error: undefined };
    },
  );
}

function wrap(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

/** The hook under test, driving real React effects, its readout rendered into the DOM. */
function Harness({ source, frameCount }: { source?: GeometrySource; frameCount?: number }) {
  const tw = useTrajectoryWindow(source, frameCount);
  return (
    <div>
      <div data-testid="frame">{tw.frame}</div>
      <div data-testid="base">{tw.currentWindow?.frame_index_base ?? "none"}</div>
      <div data-testid="displayed">{tw.displayedFrameIndex ?? "none"}</div>
      <button onClick={() => tw.ensureFrame(0)}>to0</button>
      <button onClick={() => tw.ensureFrame(1)}>to1</button>
      <button onClick={() => tw.ensureFrame(9)}>to9</button>
      <button onClick={() => tw.ensureFrame(19)}>to19</button>
    </div>
  );
}

const TOTAL = 20; // 3 windows at WINDOW_SIZE = 8: [0,8) [8,16) [16,20)
const FILE = { kind: "file" as const, fileId: "f1" };
const base = () => screen.getByTestId("base").textContent ?? "none";

describe("useTrajectoryWindow", () => {
  beforeEach(() => {
    getMock.mockReset();
  });

  it("fetches the window enclosing the requested frame; the readout index is the report's", async () => {
    mockRangedFile(TOTAL);
    render(<Harness source={FILE} frameCount={TOTAL} />, { wrapper: wrap(new QueryClient()) });

    // frame 9 → window [8,16); the readout and displayed index are the absolute report index.
    fireEvent.click(screen.getByText("to9"));
    await waitFor(() => expect(base()).toBe("8"), { timeout: 3000 });
    expect(screen.getByTestId("displayed").textContent).toBe("9");
    expect(screen.getByTestId("frame").textContent).toBe("9");
  });

  it("holds a bounded set of decoded windows — never the whole trajectory (D236 memory invariant)", async () => {
    mockRangedFile(TOTAL);
    getMock.mockClear();
    render(<Harness source={FILE} frameCount={TOTAL} />, { wrapper: wrap(new QueryClient()) });

    await waitFor(() => expect(base()).toBe("0"), { timeout: 3000 });
    fireEvent.click(screen.getByText("to9")); // → [8,16)
    await waitFor(() => expect(base()).toBe("8"), { timeout: 3000 });
    fireEvent.click(screen.getByText("to19")); // → [16,20): evicts [0,8)
    await waitFor(() => expect(base()).toBe("16"), { timeout: 3000 });
    expect(screen.getByTestId("displayed").textContent).toBe("19");

    // Scrubbing back to frame 0 must refetch [0,8) — it was evicted, proving the set never holds
    // the whole trajectory (if it held all windows, no refetch would be needed).
    const before = getMock.mock.calls.length;
    fireEvent.click(screen.getByText("to0"));
    await waitFor(() => expect(base()).toBe("0"), { timeout: 3000 });
    expect(getMock.mock.calls.length).toBeGreaterThan(before);
    // MAX_WINDOWS is the cap — the decoded-frame set handed to Mol* is bounded, never ~3 windows.
    expect(MAX_WINDOWS).toBeLessThan(Math.ceil(TOTAL / WINDOW_SIZE));
  });

  it("drops the old window when the new one loads (eviction keeps the cache at the bound)", async () => {
    mockRangedFile(TOTAL);
    render(<Harness source={FILE} frameCount={TOTAL} />, { wrapper: wrap(new QueryClient()) });

    await waitFor(() => expect(base()).toBe("0"), { timeout: 3000 });
    fireEvent.click(screen.getByText("to9"));
    await waitFor(() => expect(base()).toBe("8"), { timeout: 3000 });
    fireEvent.click(screen.getByText("to19")); // third window adopted → [0,8) is evicted
    await waitFor(() => expect(base()).toBe("16"), { timeout: 3000 });
    // Walking back across the boundary refetches, because the old window was dropped from the bound.
    const calls = getMock.mock.calls.length;
    fireEvent.click(screen.getByText("to1"));
    await waitFor(() => expect(base()).toBe("0"), { timeout: 3000 });
    expect(getMock.mock.calls.length).toBeGreaterThan(calls);
  });

  it("is inert without a source or a positive frame count (single-frame objects)", () => {
    mockRangedFile(TOTAL);
    render(<Harness frameCount={20} />, { wrapper: wrap(new QueryClient()) });
    expect(base()).toBe("none");
    expect(screen.getByTestId("frame").textContent).toBe("0");
    expect(getMock).not.toHaveBeenCalled();
  });
});