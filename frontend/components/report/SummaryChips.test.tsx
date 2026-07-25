import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ConversionReport } from "@/lib/report/types";
import { SummaryChips } from "./SummaryChips";
import completedReport from "./__fixtures__/conversion.completed.json";

const report = completedReport as unknown as ConversionReport;

/** A clean conversion: fields preserved, nothing removed, assumed, or warned. */
const lossless: ConversionReport = {
  ...report,
  removed: [],
  supplied: [],
  assumptions: [],
  warnings: [],
};

describe("SummaryChips (Part 7 §4.1)", () => {
  it("counts every category off the report arrays", () => {
    render(<SummaryChips report={report} />);
    expect(screen.getByText("2 fields preserved")).toBeInTheDocument();
    expect(screen.getByText("3 fields removed")).toBeInTheDocument();
    expect(screen.getByText("2 assumptions")).toBeInTheDocument();
    expect(screen.getByText("1 warning")).toBeInTheDocument();
  });

  it("shows a labeled zero for every category — never an unlabeled blank", () => {
    render(<SummaryChips report={lossless} />);
    expect(screen.getByText("0 fields removed")).toBeInTheDocument();
    expect(screen.getByText("0 assumptions")).toBeInTheDocument();
    expect(screen.getByText("0 warnings")).toBeInTheDocument();
  });

  it("renders a zero loss-count affirmatively (green ✓), not in its alarm color", () => {
    render(<SummaryChips report={lossless} />);
    const chip = screen.getByText("0 fields removed").parentElement as HTMLElement;
    // The affirmative rendering swaps the removed ✗ for the preserved ✓ — asserted via aria-label,
    // so the check does not depend on the color class (which color-blind readers cannot use anyway).
    expect(within(chip).getByRole("img", { name: "Preserved" })).toBeInTheDocument();
  });

  it("keeps the alarm meaning when a loss category is non-zero", () => {
    render(<SummaryChips report={report} />);
    const chip = screen.getByText("3 fields removed").parentElement as HTMLElement;
    expect(within(chip).getByRole("img", { name: "Removed" })).toBeInTheDocument();
  });
});
