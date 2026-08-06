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

  it("renders every supplied entry even when its assumption id matches nothing (row completeness)", () => {
    const orphaned = structuredClone(completedReport) as unknown as ConversionReport;
    orphaned.supplied[0].from_assumption = "A_NONEXISTENT";
    render(<ConversionReportPanel report={orphaned} />);
    // No entry may vanish through the assumption join — one rendered row per supplied element.
    expect(screen.getAllByTestId("supplied-row")).toHaveLength(orphaned.supplied.length);
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

  it("elevates the count chips into a distinct at-a-glance summary band (S4)", () => {
    render(<ConversionReportPanel report={report} />);
    const band = screen.getByTestId("report-summary-band");
    // The band *contains* the chips — the summary is the chips elevated, not a second accounting.
    expect(within(band).getByLabelText("Conversion summary")).toBeInTheDocument();
  });

  it("keeps distinct-typed sections flat — no accordion of one (S4)", () => {
    // The worked fixture has one warning and three Removed entries of distinct canonical categories,
    // so nothing repeats: grouping must not fire, and the section is a plain list.
    render(<ConversionReportPanel report={report} />);
    expect(screen.queryByTestId("report-group")).not.toBeInTheDocument();
  });

  it("groups a flood of same-code warnings into expanded-by-default disclosures (S4)", () => {
    // A trajectory-scale flood: many frames raising the same code, plus a second distinct code.
    const flood = structuredClone(completedReport) as unknown as ConversionReport;
    flood.warnings = [
      ...Array.from({ length: 5 }, (_, i) => ({
        code: "COORDINATE_REPRESENTATION_CHANGED",
        message: `Frame ${i}: coordinates rewritten.`,
        source: "capability" as const,
      })),
      { code: "FORMAT_LOSSY_NOTE", message: "Precision note.", source: "capability" as const },
    ];
    render(<ConversionReportPanel report={flood} />);

    // One disclosure per distinct code, each open (nothing buried) — the never-buried promise.
    const groups = screen.getAllByTestId("report-group");
    expect(groups).toHaveLength(2);
    for (const group of groups) {
      expect(group).toHaveAttribute("open");
    }
    // Row completeness survives grouping: one warning row per warning, every verbatim message shown.
    expect(screen.getAllByTestId("warning-row")).toHaveLength(flood.warnings.length);
    for (const warning of flood.warnings) {
      expect(screen.getByText(warning.message)).toBeInTheDocument();
    }
    // The repeated code heads its group once, with its count.
    expect(within(groups[0]).getByText("COORDINATE_REPRESENTATION_CHANGED")).toBeInTheDocument();
    expect(within(groups[0]).getByText("(5)")).toBeInTheDocument();
  });

  it("groups a lengthy Removed list by canonical category, still expanded (S4)", () => {
    const many = structuredClone(completedReport) as unknown as ConversionReport;
    many.removed = [
      { path: "dynamics.forces", reason: "no forces", detail: null },
      { path: "dynamics.velocities", reason: "no velocities", detail: null },
      { path: "electronic.total_energy", reason: "no energy", detail: null },
    ];
    render(<ConversionReportPanel report={many} />);

    // "dynamics" repeats → group; two categories → two disclosures, both open.
    const groups = screen.getAllByTestId("report-group");
    expect(groups).toHaveLength(2);
    for (const group of groups) expect(group).toHaveAttribute("open");
    // No Removed row is lost to the regrouping, and each reason stays verbatim.
    expect(screen.getAllByTestId("removed-row")).toHaveLength(many.removed.length);
    for (const entry of many.removed) {
      expect(screen.getByText(entry.reason)).toBeInTheDocument();
    }
    // The category heads its group in plain words, not a raw path.
    expect(within(groups[0]).getByText("Dynamics")).toBeInTheDocument();
  });

  it("omits empty loss sections but never the affirmative summary (empty-state)", () => {
    // A clean conversion: everything preserved, nothing removed, assumed, or warned. The loss
    // sections are absent (a heading with zero rows would be noise), but the always-present summary
    // chips still account for the zeros — so omission is never a silent blank.
    const lossless: ConversionReport = {
      ...report,
      removed: [],
      supplied: [],
      assumptions: [],
      warnings: [],
    };
    render(<ConversionReportPanel report={lossless} />);
    expect(screen.getAllByTestId("preserved-row")).toHaveLength(report.preserved.length);
    expect(screen.queryByTestId("removed-row")).not.toBeInTheDocument();
    expect(screen.queryByTestId("assumption-row")).not.toBeInTheDocument();
    expect(screen.queryByTestId("warning-row")).not.toBeInTheDocument();
    // The affirmative zero accounting survives in the chips.
    expect(screen.getByText("0 fields removed")).toBeInTheDocument();
  });
});
