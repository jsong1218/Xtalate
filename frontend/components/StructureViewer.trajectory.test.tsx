/**
 * StructureViewer trajectory gating tests (v1.6 M61-S1, D236): the frame scrubber appears **iff**
 * the object is multi-frame (`frame_count > 1`) **and** the caller supplied a read
 * `trajectorySource`; a single-frame object renders exactly as M60 (static, no scrubber). The
 * multi-frame path drives the sliding-window hook, so these tests wrap a QueryClient and mock the
 * ranged geometry endpoint (Mol* is stubbed exactly as in StructureViewer.test.tsx).
 */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ReactNode } from "react";
import type { Schemas } from "@/lib/api/client";
import { StructureViewer } from "./StructureViewer";

vi.mock("./StructureViewerMolstar", () => ({
  default: ({ geometry }: { geometry: Schemas["GeometryResponse"] }) => (
    <div data-testid="molstar-mount" data-atoms={geometry.species.length} />
  ),
}));

/** The fake client answers any file-geometry range with the requested window. */
const { getMock } = vi.hoisted(() => ({ getMock: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiClient: { GET: getMock } }));

function wrap(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const species = ["C", "H"];

/** A 6-frame celled geometry — multi-frame (scrubber on). */
const multiFrameFixture: Schemas["GeometryResponse"] = {
  source: { format_id: "extxyz", filename: "relax.extxyz" },
  species,
  cell: null,
  frame_index_base: 0,
  frame_count: 6,
  frames: Array.from({ length: 6 }, (_, i) => ({
    index: i,
    positions: [
      [i, 0, 0],
      [i + 1.1, 0, 0],
    ],
    cell: null,
  })),
};

/** The same object collapsed to a single frame (frame_count 1 — scrubber off). */
const singleFrameFixture: Schemas["GeometryResponse"] = {
  ...multiFrameFixture,
  frame_count: 1,
  frames: [multiFrameFixture.frames![0]],
};

beforeEach(() => {
  getMock.mockReset();
  getMock.mockImplementation(
    async (
      _url: string,
      { params }: { params: { query: { frames: string } } },
    ) => {
      const [s, e] = params.query.frames.split(":").map(Number);
      const frames = (
        multiFrameFixture.frames as { index: number; positions: number[][]; cell: null }[]
      )
        .slice(s, e)
        .map((f) => ({ ...f, index: f.index }));
      return { data: { ...multiFrameFixture, frame_index_base: s, frames }, error: undefined };
    },
  );
});

const client = new QueryClient();
const FILE_SOURCE = { kind: "file" as const, fileId: "f1" };

describe("StructureViewer trajectory gating", () => {
  it("shows the frame scrubber for a multi-frame object with a read source", async () => {
    render(
      <StructureViewer geometry={multiFrameFixture} trajectorySource={FILE_SOURCE} />,
      { wrapper: wrap(client) },
    );
    // The readout labels a frame number ("0 / 6"), never a time.
    const range = await screen.findByRole("slider", { name: /Trajectory frame/ });
    expect(range).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("0 / 6");
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("renders no scrubber for a single-frame object even with a read source", async () => {
    render(
      <StructureViewer geometry={singleFrameFixture} trajectorySource={FILE_SOURCE} />,
      { wrapper: wrap(client) },
    );
    await screen.findByTestId("molstar-mount");
    expect(screen.queryByRole("slider", { name: /Trajectory frame/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Play|Pause/ })).toBeNull();
  });

  it("renders no scrubber for a multi-frame object without a read source", async () => {
    render(<StructureViewer geometry={multiFrameFixture} />, { wrapper: wrap(client) });
    await screen.findByTestId("molstar-mount");
    expect(screen.queryByRole("slider", { name: /Trajectory frame/ })).toBeNull();
  });
});