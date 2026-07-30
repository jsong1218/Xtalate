import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SummaryCountChips } from "./SummaryChips";

/**
 * `SummaryCountChips` is the counts-driven core the report panel and the history row share (slice
 * M33-S2). The history endpoint sends `summary_counts` (four integers), never the full report
 * arrays, so the row must be able to render the *exact same* four chips from counts alone — reusing
 * the design language, not re-drawing it. These tests pin the counts contract; the report-driven
 * `SummaryChips` wrapper keeps its own suite.
 */
describe("SummaryCountChips (Part 7 §4.1, counts core)", () => {
  it("labels every category from the counts, even at zero — never an unlabeled blank", () => {
    render(
      <SummaryCountChips counts={{ preserved: 5, removed: 0, assumptions: 0, warnings: 0 }} />,
    );
    expect(screen.getByText("5 fields preserved")).toBeInTheDocument();
    expect(screen.getByText("0 fields removed")).toBeInTheDocument();
    expect(screen.getByText("0 assumptions")).toBeInTheDocument();
    expect(screen.getByText("0 warnings")).toBeInTheDocument();
  });

  it("renders a zero loss-count affirmatively (green ✓), like the report panel", () => {
    render(
      <SummaryCountChips counts={{ preserved: 5, removed: 0, assumptions: 0, warnings: 0 }} />,
    );
    const chip = screen.getByText("0 fields removed").parentElement as HTMLElement;
    expect(within(chip).getByRole("img", { name: "Preserved" })).toBeInTheDocument();
  });

  it("keeps the alarm meaning when a loss category is non-zero", () => {
    render(
      <SummaryCountChips counts={{ preserved: 1, removed: 3, assumptions: 2, warnings: 1 }} />,
    );
    const chip = screen.getByText("3 fields removed").parentElement as HTMLElement;
    expect(within(chip).getByRole("img", { name: "Removed" })).toBeInTheDocument();
  });

  it("treats a missing count key as zero (the row never crashes on a sparse map)", () => {
    render(<SummaryCountChips counts={{ preserved: 2 }} />);
    expect(screen.getByText("2 fields preserved")).toBeInTheDocument();
    expect(screen.getByText("0 fields removed")).toBeInTheDocument();
  });
});
