import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ConversionReport } from "@/lib/report/types";
import { RefusalPanel } from "./RefusalPanel";
import refusedReport from "./__fixtures__/conversion.refused.json";
import completedReport from "./__fixtures__/conversion.completed.json";

const refused = refusedReport as unknown as ConversionReport;
const completed = completedReport as unknown as ConversionReport;

describe("RefusalPanel (Part 4 §4 / Part 7 §4.5)", () => {
  it("shows the refusal code verbatim and its message", () => {
    render(<RefusalPanel report={refused} />);
    expect(screen.getByText("RECOVERY_REQUIRED")).toBeInTheDocument();
    expect(screen.getByText(refused.refusal!.message)).toBeInTheDocument();
  });

  it("renders one row per unresolved scenario — counted against the array", () => {
    render(<RefusalPanel report={refused} />);
    expect(screen.getAllByTestId("unresolved-scenario")).toHaveLength(
      refused.refusal!.unresolved_scenarios.length,
    );
  });

  it("names each unresolved scenario in plain language, code one step away", () => {
    render(<RefusalPanel report={refused} />);
    // "frame_selection" → "Pick which snapshot to keep"; "missing_lattice" → "No simulation cell".
    expect(screen.getByText("Pick which snapshot to keep")).toBeInTheDocument();
    expect(screen.getByText("No simulation cell")).toBeInTheDocument();
    // The raw codes are shown (as the badge one step away), but never as the only label.
    expect(screen.getByText("frame_selection")).toBeInTheDocument();
    expect(screen.getByText("missing_lattice")).toBeInTheDocument();
  });

  it("shows the honest, pair-specific choices a caller could supply", () => {
    render(<RefusalPanel report={refused} />);
    for (const opt of ["first", "last", "index", "manual_input", "upload_reference", "bounding_box"]) {
      expect(screen.getByText(opt)).toBeInTheDocument();
    }
  });

  it("still renders the report body — what the refused conversion would keep and drop", () => {
    render(<RefusalPanel report={refused} />);
    // The Removed section from the embedded Conversion Report panel is present.
    expect(screen.getAllByTestId("removed-row")).toHaveLength(refused.removed.length);
    expect(screen.getByText("Target format 'poscar' cannot store dynamics.forces.")).toBeInTheDocument();
  });

  it("renders nothing for a non-refused report (defensive)", () => {
    const { container } = render(<RefusalPanel report={completed} />);
    expect(container).toBeEmptyDOMElement();
  });
});
