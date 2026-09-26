import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchLayout } from "./WorkbenchLayout";

// Toolbar mounts the ⌘K palette + theme/notify toggles, which need router + provider context the
// standalone shell test doesn't set up (see Toolbar.test.tsx) — that wiring is exercised there.
// This test only cares that the toolbar region exists and renders Toolbar's `banner` landmark, so
// Toolbar is mocked to a bare banner stand-in.
vi.mock("@/components/shell/Toolbar", () => ({
  Toolbar: () => <header>toolbar stub</header>,
}));

describe("WorkbenchLayout", () => {
  it("renders the five workbench regions", () => {
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(screen.getByRole("banner")).toBeInTheDocument(); // toolbar
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("complementary")).toBeInTheDocument(); // inspector
    expect(screen.getByRole("contentinfo")).toBeInTheDocument(); // status bar
    expect(screen.getByText("center")).toBeInTheDocument();
  });

  it("makes the center region focusable for the skip-link target", () => {
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(screen.getByRole("main")).toHaveAttribute("tabIndex", "-1");
  });

  it("reserves an empty, unlabeled sources-rail column instead of a competing landmark", () => {
    // `app/f/[file_id]/layout.tsx` already renders the real, populated `<SourceRail
    // fileId=.../>` (an `<aside aria-label="Source file">`) as part of `{children}`, which now
    // renders inside this shell's center. If the shell's own rail column carried a "Sources"
    // landmark/heading too, every `/f/[file_id]/*` page would show two competing Sources panels
    // (a live regression caught in review). So the column must render with no accessible name and
    // no landmark role of its own — just reserved width/chrome — until Task 9 gives it real,
    // non-duplicated content.
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(screen.getByTestId("wb-sources-placeholder")).toBeInTheDocument();
    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Sources" })).not.toBeInTheDocument();
    // Exactly one complementary landmark remains: the Inspector stub.
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
  });
});
