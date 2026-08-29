/**
 * StructureTab tests (v1.6 M60-S1): the tab seam renders the honest states — the viewer mounts
 * when geometry is ready, the loading affordance shows while loading, and the expired/error
 * states render their copy with **no viewer**. The Mol* chunk is stubbed exactly as in
 * StructureViewer.test.tsx (WebGL cannot run under jsdom); the real render is proven by the e2e
 * journey against the live stack.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";
import { StructureTab } from "./StructureTab";

vi.mock("./StructureViewerMolstar", () => ({
  default: ({ geometry }: { geometry: CanonicalGeometry }) => (
    <div
      data-testid="molstar-mount"
      data-atoms={geometry.species.length}
      data-has-cell={geometry.cell ? "true" : "false"}
    />
  ),
}));

/** A celled 2-atom geometry fixture — the worked-example shape (reused from StructureViewer.test). */
const fixture: CanonicalGeometry = {
  source: { format_id: "extxyz", filename: "worked.xyz" },
  species: ["C", "H"],
  cell: [
    [6, 0, 0],
    [0, 6, 0],
    [0, 0, 6],
  ],
  frame_index_base: 0,
  frame_count: 1,
  frames: [
    {
      index: 0,
      positions: [
        [0, 0, 0],
        [1.1, 0, 0],
      ],
      cell: [
        [6, 0, 0],
        [0, 6, 0],
        [0, 0, 6],
      ],
    },
  ],
};

/** A service error envelope, the shape the 410 geometry responses carry (D232). */
function expiredEnvelope(code: "FILE_EXPIRED" | "OUTPUT_EXPIRED") {
  return {
    error: {
      code,
      message:
        code === "OUTPUT_EXPIRED"
          ? "The output bytes have expired."
          : "The uploaded file has expired.",
      details: {},
      request_id: "e2e-expired-geometry",
      documentation_url: "http://localhost:8000/docs/errors",
    },
  };
}

describe("StructureTab", () => {
  it("mounts the viewer fed by the geometry when ready", async () => {
    render(<StructureTab geometryState={{ status: "ready", geometry: fixture }} />);
    const mount = await screen.findByTestId("molstar-mount");
    expect(mount).toHaveAttribute("data-atoms", "2");
  });

  it("shows the loading affordance and no viewer while loading", () => {
    render(<StructureTab geometryState={{ status: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading structure…");
    expect(screen.queryByTestId("molstar-mount")).toBeNull();
  });

  it("renders the expired-output copy and no viewer when the output bytes are gone", () => {
    render(
      <StructureTab
        geometryState={{ status: "error", error: expiredEnvelope("OUTPUT_EXPIRED") }}
      />,
    );
    expect(
      screen.getByText(/The output bytes have expired; the reports below remain the complete record/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("molstar-mount")).toBeNull();
  });

  it("renders the expired-file copy and no viewer when the source bytes are gone", () => {
    render(
      <StructureTab
        geometryState={{ status: "error", error: expiredEnvelope("FILE_EXPIRED") }}
      />,
    );
    expect(
      screen.getByText(/This file's bytes have expired; the reports below remain the complete record/),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("molstar-mount")).toBeNull();
  });

  it("renders the service error envelope and no viewer for any other geometry failure", () => {
    render(
      <StructureTab
        geometryState={{
          status: "error",
          error: {
            error: {
              code: "NETWORK_ERROR",
              message: "Could not reach the server.",
              details: {},
              request_id: "req-3",
              documentation_url: "http://localhost:8000/docs/errors",
            },
          },
        }}
      />,
    );
    expect(screen.getByText("NETWORK_ERROR")).toBeInTheDocument();
    expect(screen.queryByTestId("molstar-mount")).toBeNull();
  });
});
