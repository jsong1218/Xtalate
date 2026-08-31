import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceTabs } from "./WorkspaceTabs";

/**
 * The workspace tab bar (UI redesign S2, D244; D-R1/D-R5): every surface is a route, so tabs are
 * always clickable; the active tab wears the accent-text token and `aria-current="page"`. The
 * Report tab needs a conversion id in its URL, so it links only while the workspace is on a report
 * route and otherwise renders an inert disabled tab — never a link that would 404.
 */
const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn(() => "/f/file-1") }));
vi.mock("next/navigation", () => ({ usePathname }));

describe("WorkspaceTabs", () => {
  it("offers the four always-clickable tabs plus the Report slot, pointing at their routes", () => {
    render(<WorkspaceTabs fileId="file-1" />);
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
    // No report URL exists off a report route — the slot is inert, not a 404 link.
    expect(screen.getByText("Report")).toHaveAttribute("aria-disabled", "true");
  });

  it("marks the active tab with aria-current and the accent-text token", () => {
    usePathname.mockReturnValue("/f/file-1/convert");
    render(<WorkspaceTabs fileId="file-1" />);
    const active = screen.getByRole("link", { name: "Convert" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toContain("text-accent-text");
    expect(screen.getByRole("link", { name: "Inspect" })).not.toHaveAttribute("aria-current");
  });

  it("links the Report tab while on a report route", () => {
    usePathname.mockReturnValue("/f/file-1/report/cnv-42");
    render(<WorkspaceTabs fileId="file-1" />);
    const report = screen.getByRole("link", { name: "Report" });
    expect(report).toHaveAttribute("aria-current", "page");
    expect(report).toHaveAttribute("href", "/f/file-1/report/cnv-42");
  });
});
