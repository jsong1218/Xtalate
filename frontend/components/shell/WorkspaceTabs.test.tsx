import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceTabs } from "./WorkspaceTabs";

/**
 * The center tab strip (v2.0 addendums, Task 11; design spec §"Shell architecture"): Report leads,
 * then Structure/Convert/Analysis, then the bare overview ("Inspect") tab kept from the pre-Task-11
 * component. Every routed tab is a real `<Link>`; the active one wears the accent-text token and
 * `aria-current="page"`. There is no `/f/[file_id]/compare` route, so no Compare tab exists (mirrors
 * the `Toolbar`'s own Validate/Repair omission). The Report tab needs a conversion id in its URL, so
 * it links only while the workspace is on a report route and otherwise renders an inert disabled
 * tab — never a link that would 404.
 */
const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn(() => "/f/file-1") }));
vi.mock("next/navigation", () => ({ usePathname }));

describe("WorkspaceTabs", () => {
  it("offers Report first, then Structure/Convert/Analysis, then Inspect, pointing at their routes", () => {
    render(<WorkspaceTabs fileId="file-1" />);
    const links = screen.getAllByRole("link");
    // Order matters: Report leads (design intent), Inspect trails.
    expect(links.map((l) => l.textContent)).toEqual([
      "Structure",
      "Convert",
      "Analysis",
      "Inspect",
    ]);
    // No report URL exists off a report route — the slot is inert, not a 404 link.
    expect(screen.getByText("Report")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("link", { name: "Inspect" })).toHaveAttribute("href", "/f/file-1");
    expect(screen.getByRole("link", { name: "Structure" })).toHaveAttribute(
      "href",
      "/f/file-1/structure",
    );
    expect(screen.getByRole("link", { name: "Convert" })).toHaveAttribute("href", "/f/file-1/convert");
    expect(screen.getByRole("link", { name: "Analysis" })).toHaveAttribute(
      "href",
      "/f/file-1/analysis",
    );
  });

  it("never renders a Compare tab (no /f/[file_id]/compare route exists)", () => {
    render(<WorkspaceTabs fileId="file-1" />);
    expect(screen.queryByText("Compare")).not.toBeInTheDocument();
  });

  it("marks the active tab with aria-current and the accent-text token", () => {
    usePathname.mockReturnValue("/f/file-1/convert");
    render(<WorkspaceTabs fileId="file-1" />);
    const active = screen.getByRole("link", { name: "Convert" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toContain("text-accent-text");
    expect(screen.getByRole("link", { name: "Inspect" })).not.toHaveAttribute("aria-current");
  });

  it("marks Inspect (the bare overview route) as active on the overview page", () => {
    usePathname.mockReturnValue("/f/file-1");
    render(<WorkspaceTabs fileId="file-1" />);
    const active = screen.getByRole("link", { name: "Inspect" });
    expect(active).toHaveAttribute("aria-current", "page");
  });

  it("links the Report tab while on a report route, as the first tab", () => {
    usePathname.mockReturnValue("/f/file-1/report/cnv-42");
    render(<WorkspaceTabs fileId="file-1" />);
    const report = screen.getByRole("link", { name: "Report" });
    expect(report).toHaveAttribute("aria-current", "page");
    expect(report).toHaveAttribute("href", "/f/file-1/report/cnv-42");
    const links = screen.getAllByRole("link");
    expect(links[0]).toBe(report);
  });
});
