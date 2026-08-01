import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ValidationReport } from "@/lib/report/types";
import { ValidationReportPanel } from "./ValidationReportPanel";
import passedReport from "./__fixtures__/validation.passed.json";

/**
 * The Validation Report panel, proven against the Part 4 §5 worked report's validation output
 * committed verbatim as a fixture. The load-bearing assertion is the same as the Conversion panel's:
 * **one row per check, counted against the fixture array** — a silently dropped check is itself a
 * fidelity finding gone missing.
 */
const report = passedReport as unknown as ValidationReport;

describe("ValidationReportPanel (Part 5 §3 / Part 7 §4.4)", () => {
  it("renders one row per check — the count matches the report array", () => {
    render(<ValidationReportPanel report={report} />);
    expect(screen.getAllByTestId("check-row")).toHaveLength(report.checks.length);
  });

  it("renders every check even when two share a check_id — no row lost to a key collision", () => {
    // Rows are keyed by check_id + index (the v0.7 review): a check_id alone is not guaranteed
    // unique across a list, and a duplicate React key silently drops a sibling. Duplicating a
    // check_id must still render both rows — a reported check is never dropped by the key.
    const dup = report.checks[0];
    const withDupes: ValidationReport = { ...report, checks: [...report.checks, dup] };
    render(<ValidationReportPanel report={withDupes} />);
    expect(screen.getAllByTestId("check-row")).toHaveLength(report.checks.length + 1);
  });

  it("shows each check message verbatim, never paraphrased", () => {
    render(<ValidationReportPanel report={report} />);
    for (const check of report.checks) {
      expect(screen.getByText(check.message)).toBeInTheDocument();
    }
  });

  it("shows a skipped check with its skip_reason in plain sight — never hidden", () => {
    render(<ValidationReportPanel report={report} />);
    const skipped = report.checks.find((c) => c.status === "skipped");
    expect(skipped?.skip_reason).toBeTruthy();
    // The reason text is present, and its row carries the "Skipped" icon (not omitted, not silent).
    expect(screen.getByText(new RegExp(skipped!.skip_reason as string, "i"))).toBeInTheDocument();
    const skippedRow = screen.getByText(skipped!.message).closest("li") as HTMLElement;
    expect(within(skippedRow).getByRole("img", { name: "Skipped" })).toBeInTheDocument();
  });

  it("keeps measurements and tolerances behind a per-row disclosure", () => {
    render(<ValidationReportPanel report={report} />);
    // positions_rmsd carries both measured numbers and a tolerance profile → a <details> exists.
    const rmsdRow = screen
      .getByText("RMSD 0.000e+00 Å over 1 frame(s), within representational precision.")
      .closest("li") as HTMLElement;
    expect(within(rmsdRow).getByText("Measurements & tolerances")).toBeInTheDocument();
    // The representational-precision bound is present in the disclosed content.
    expect(within(rmsdRow).getByText("representational_bound_ang")).toBeInTheDocument();
  });

  it("heads the panel with the aggregate status in plain language", () => {
    render(<ValidationReportPanel report={report} />);
    expect(screen.getByText("Validation passed")).toBeInTheDocument();
  });

  it("headlines a failed report as failed, not passed", () => {
    const failed: ValidationReport = {
      ...report,
      status: "failed",
      checks: report.checks.map((c, i) =>
        i === 2 ? { ...c, status: "fail", message: "RMSD 4.2e-01 Å exceeds fail threshold." } : c,
      ),
    };
    render(<ValidationReportPanel report={failed} />);
    expect(screen.getByText("Validation failed")).toBeInTheDocument();
    const failRow = screen.getByText("RMSD 4.2e-01 Å exceeds fail threshold.").closest("li") as HTMLElement;
    expect(within(failRow).getByRole("img", { name: "Failed" })).toBeInTheDocument();
  });
});
