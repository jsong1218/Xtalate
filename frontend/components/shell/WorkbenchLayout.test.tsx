import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkbenchLayout } from "./WorkbenchLayout";

// AppHeader mounts the ⌘K palette + theme/notify toggles, which need router + provider context the
// standalone shell test doesn't set up (see AppHeader.test.tsx) — that wiring is exercised there.
// This test only cares that the toolbar region exists and renders AppHeader's `banner` landmark, so
// AppHeader is mocked to a bare banner stand-in, matching the temporary-render decision (Task 8
// replaces AppHeader with the real Toolbar).
vi.mock("@/components/shell/AppHeader", () => ({
  AppHeader: () => <header>app header stub</header>,
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
});
