/**
 * StructureViewer tests (v1.6 M59-S2): the bonds heuristic badge appears iff the toggle is on
 * (D234), and the geometry reaches the Mol\* mount. The Mol\* plugin itself is WebGL and cannot
 * run under jsdom — the `ssr: false` dynamic chunk is stubbed here, and the real render is proven
 * by the e2e journey against the live stack.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { CanonicalGeometry } from "@/lib/geometry/useGeometry";
import { StructureViewer } from "./StructureViewer";

vi.mock("./StructureViewerMolstar", () => ({
  default: ({
    geometry,
    suppliedCell,
    bonds,
  }: {
    geometry: CanonicalGeometry;
    suppliedCell?: boolean;
    bonds?: boolean;
  }) => (
    <div
      data-testid="molstar-mount"
      data-atoms={geometry.species.length}
      data-has-cell={geometry.cell ? "true" : "false"}
      data-cell-supplied={suppliedCell ? "true" : "false"}
      data-bonds={String(Boolean(bonds))}
    />
  ),
}));

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

/** The same object with no lattice anywhere — the `cell: null` case (P3). */
const cellLessFixture: CanonicalGeometry = {
  ...fixture,
  cell: null,
  frames: fixture.frames!.map((f) => ({ ...f, cell: null })),
};

describe("StructureViewer", () => {
  it("renders the Mol* mount fed by the geometry, with bonds off by default", async () => {
    render(<StructureViewer geometry={fixture} />);
    const mount = await screen.findByTestId("molstar-mount");
    expect(mount).toHaveAttribute("data-atoms", "2");
    expect(screen.queryByText(/display heuristic/)).toBeNull();
  });

  it("renders the species legend and no cell-less caption for a celled geometry", async () => {
    render(<StructureViewer geometry={fixture} />);
    await screen.findByTestId("molstar-mount");
    // Legend completeness: exactly the species present, each with its label as text.
    expect(screen.getAllByTestId(/^legend-row-/)).toHaveLength(2);
    expect(screen.getByTestId("legend-row-C")).toHaveTextContent("C");
    expect(screen.getByTestId("legend-row-H")).toHaveTextContent("H");
    expect(screen.queryByTestId("no-cell-caption")).toBeNull();
  });

  it("renders the no-simulation-cell caption and no box for a cell-less geometry (P3)", async () => {
    render(<StructureViewer geometry={cellLessFixture} />);
    const mount = await screen.findByTestId("molstar-mount");
    // The caption says why there is no box…
    expect(screen.getByTestId("no-cell-caption")).toHaveTextContent(
      /declares no simulation cell/
    );
    // …and the loader/render path receives a cell-less geometry — no cell wireframe possible.
    expect(mount).toHaveAttribute("data-has-cell", "false");
  });

  it("shows the bonds heuristic badge iff the toggle is on", async () => {
    render(<StructureViewer geometry={fixture} />);
    await screen.findByTestId("molstar-mount");
    const toggle = screen.getByRole("button", { name: /Show bonds heuristic/ });
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(
        screen.getByText("Bonds are a display heuristic, not file content")
      ).toBeInTheDocument()
    );
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.queryByText(/display heuristic/)).toBeNull()
    );
  });

  it("lays the viewer out as annotations / canvas / controls rows", () => {
    render(<StructureViewer geometry={fixture} />);
    expect(screen.getByTestId("viewer-annotations")).toBeInTheDocument();
    expect(screen.getByTestId("viewer-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("viewer-controls")).toBeInTheDocument();
  });

  it("keeps the bonds heuristic badge and drives the render when toggled on", async () => {
    render(<StructureViewer geometry={fixture} />);
    const mount = await screen.findByTestId("molstar-mount");
    expect(mount).toHaveAttribute("data-bonds", "false");
    const toggle = screen.getByRole("button", { name: /show bonds heuristic/i });
    await userEvent.click(toggle);
    expect(screen.getByText(/display heuristic, not file content/i)).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    // The prop genuinely reaches the mount — not just the badge, which the previous test covers.
    expect(mount).toHaveAttribute("data-bonds", "true");
  });

  it("offers reset-view and expand controls", () => {
    render(<StructureViewer geometry={fixture} />);
    expect(screen.getByRole("button", { name: /reset view/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand/i })).toBeInTheDocument();
  });

  it("opens a fullscreen overlay on expand and closes on Escape", async () => {
    render(<StructureViewer geometry={fixture} />);
    await userEvent.click(screen.getByRole("button", { name: /expand/i }));
    expect(screen.getByRole("dialog", { name: /structure viewer/i })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("traps Tab focus inside the expand overlay, away from the background controls", async () => {
    render(<StructureViewer geometry={fixture} />);
    // A background control that must stay unreachable by keyboard while the overlay is open.
    const resetButton = screen.getByRole("button", { name: /reset view/i });
    await userEvent.click(screen.getByRole("button", { name: /expand/i }));
    const closeButton = screen.getByRole("button", { name: /close/i });
    closeButton.focus();
    // The Close button is the dialog's only focusable element in this fixture (the mocked mount
    // renders no interactive content); Tab must cycle back to it, never escape to `resetButton`.
    await userEvent.tab();
    expect(document.activeElement).toBe(closeButton);
    expect(document.activeElement).not.toBe(resetButton);
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(closeButton);
  });

  it("does not re-run the overlay's mount effect (and re-steal focus) on an unrelated re-render", async () => {
    const { rerender } = render(<StructureViewer geometry={fixture} />);
    await userEvent.click(screen.getByRole("button", { name: /expand/i }));
    const closeButton = screen.getByRole("button", { name: /close/i });
    closeButton.focus();
    expect(document.activeElement).toBe(closeButton);
    // Re-rendering the parent (as a bonds toggle or a Compare-tab frame tick would) must not hand
    // focus back to the dialog container — that would mean `onClose` was unstable and the mount
    // effect re-ran, corrupting the eventual focus-restore-on-close target.
    rerender(<StructureViewer geometry={fixture} />);
    expect(document.activeElement).toBe(closeButton);
  });
});
