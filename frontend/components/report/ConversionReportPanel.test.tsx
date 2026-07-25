import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ConversionReport } from "@/lib/report/types";
import { ConversionReportPanel } from "./ConversionReportPanel";
import completedReport from "./__fixtures__/conversion.completed.json";

/**
 * The Conversion Report panel, proven against the Part 4 §5 worked report committed verbatim as a
 * fixture. The load-bearing assertions are the **row counts against the fixture arrays**: if a
 * section ever silently drops an entry, the count diverges and the test fails loudly — that is the
 * whole point of the panel (no silent loss, including in the loss report itself).
 */
const report = completedReport as unknown as ConversionReport;

describe("ConversionReportPanel (Part 4 §2 / Part 7 §4.3)", () => {
  it("renders one row per entry in every section — counts match the report arrays", () => {
    render(<ConversionReportPanel report={report} />);

    expect(screen.getAllByTestId("preserved-row")).toHaveLength(report.preserved.length);
    expect(screen.getAllByTestId("removed-row")).toHaveLength(report.removed.length);
    expect(screen.getAllByTestId("assumption-row")).toHaveLength(report.assumptions.length);
    expect(screen.getAllByTestId("supplied-row")).toHaveLength(report.supplied.length);
    expect(screen.getAllByTestId("warning-row")).toHaveLength(report.warnings.length);
  });

  it("shows each Removed reason verbatim, never paraphrased", () => {
    render(<ConversionReportPanel report={report} />);
    for (const entry of report.removed) {
      expect(screen.getByText(entry.reason)).toBeInTheDocument();
    }
  });

  it("groups Supplied fields under the Assumption that authorized them", () => {
    render(<ConversionReportPanel report={report} />);
    // Every supplied row is nested inside an assumption row, never orphaned as a sibling.
    const assumptionRows = screen.getAllByTestId("assumption-row");
    const rowsWithSupplied = assumptionRows.filter(
      (row) => within(row).queryAllByTestId("supplied-row").length > 0,
    );
    // A2 (missing_lattice) authorized both supplied fields; A1 (frame_selection) supplied nothing.
    expect(rowsWithSupplied).toHaveLength(1);
    expect(within(rowsWithSupplied[0]).getAllByTestId("supplied-row")).toHaveLength(2);
  });

  it("leads with the source → target header from the report, not a hard-coded string", () => {
    render(<ConversionReportPanel report={report} />);
    expect(screen.getByText(report.source.filename)).toBeInTheDocument();
    expect(screen.getByText(report.target.filename)).toBeInTheDocument();
  });

  it("resolves field paths through the plain-language mapping, not raw codes", () => {
    render(<ConversionReportPanel report={report} />);
    // "atoms.symbols" → "Chemical species (symbols)"; the raw path is not the primary label.
    expect(screen.getByText("Chemical species (symbols)")).toBeInTheDocument();
    expect(screen.queryByText("atoms.symbols")).not.toBeInTheDocument();
  });
});
