import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchLayout } from "./WorkbenchLayout";

// Toolbar mounts the ⌘K palette + theme/notify toggles, which need router + provider context the
// standalone shell test doesn't set up (see Toolbar.test.tsx) — that wiring is exercised there.
// This test only cares that the toolbar region exists and renders Toolbar's `banner` landmark, so
// Toolbar is mocked to a bare banner stand-in.
vi.mock("@/components/shell/Toolbar", () => ({
  Toolbar: () => <header>toolbar stub</header>,
}));

// SourceRail (Task 9) needs react-query + the recents localStorage source (see its own test) —
// irrelevant to this shell-structure test, so it is mocked to a bare nav stand-in that still
// reports the props WorkbenchLayout is responsible for deriving/owning.
const { sourceRailProps } = vi.hoisted(() => ({ sourceRailProps: vi.fn() }));
vi.mock("@/components/shell/SourceRail", () => ({
  SourceRail: (props: { activeFileId: string | null; collapsed: boolean; onToggle: () => void }) => {
    sourceRailProps(props);
    return <nav aria-label="Sources">sources rail stub</nav>;
  },
}));

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn(() => "/") }));
vi.mock("next/navigation", () => ({ usePathname }));

describe("WorkbenchLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePathname.mockReturnValue("/");
    window.localStorage.clear();
  });

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

  it("renders the real, single Sources rail — no competing landmark", () => {
    // Task 9: the shell owns one persistent Sources rail (`SourceRail`, mocked above). Before this
    // task the column was an empty, unlabeled placeholder while `app/f/[file_id]/layout.tsx` (now
    // changed — see that file) rendered its own per-file rail inline; that duplicate is gone, so
    // exactly one "Sources" landmark exists, alongside exactly one Inspector landmark.
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(screen.getByRole("navigation", { name: "Sources" })).toBeInTheDocument();
    expect(screen.queryByTestId("wb-sources-placeholder")).not.toBeInTheDocument();
    // Exactly one complementary landmark remains: the Inspector stub.
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
  });

  it("derives the active file id from the route and passes it to SourceRail", () => {
    usePathname.mockReturnValue("/f/file-42/structure");
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(sourceRailProps).toHaveBeenCalledWith(
      expect.objectContaining({ activeFileId: "file-42" }),
    );
  });

  it("passes no active file id off a /f/ route", () => {
    usePathname.mockReturnValue("/formats");
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(sourceRailProps).toHaveBeenCalledWith(expect.objectContaining({ activeFileId: null }));
  });

  it("toggles the collapsed flag it owns when SourceRail's onToggle fires", () => {
    render(
      <WorkbenchLayout>
        <p>center</p>
      </WorkbenchLayout>,
    );
    expect(sourceRailProps).toHaveBeenCalledWith(expect.objectContaining({ collapsed: false }));
    const { onToggle } = sourceRailProps.mock.calls[sourceRailProps.mock.calls.length - 1][0];
    act(() => {
      onToggle();
    });
    expect(sourceRailProps).toHaveBeenLastCalledWith(
      expect.objectContaining({ collapsed: true }),
    );
  });
});
