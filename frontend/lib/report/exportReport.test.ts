import { describe, expect, it } from "vitest";
import type { ConversionReport } from "./types";
import completedReport from "@/components/report/__fixtures__/conversion.completed.json";
import { reportToJson, reportToMarkdown } from "./exportReport";

const report = completedReport as unknown as ConversionReport;

/**
 * The export serializers (UI redesign S3, D245) — pure functions of the report model, so the tests
 * run against the strings themselves. Two load-bearing properties:
 *
 *  - **Faithfulness.** JSON is the model verbatim (a loss can never be serialized away); Markdown
 *    contains every row, with the engine's reasons/descriptions verbatim and the canonical path
 *    always present beside the plain label.
 *  - **Determinism.** The same report always yields the same string — the e2e journey's
 *    "Copy-as-JSON produces the expected string" is built on this module, not on DOM scraping.
 */
describe("reportToJson", () => {
  it("serializes the report model verbatim, pretty-printed", () => {
    const out = reportToJson(report);
    expect(JSON.parse(out)).toEqual(report);
    expect(out).toContain("\n  ");
  });

  it("never drops a row from the serialized model", () => {
    const parsed = JSON.parse(reportToJson(report)) as ConversionReport;
    expect(parsed.preserved).toHaveLength(report.preserved.length);
    expect(parsed.removed).toHaveLength(report.removed.length);
    expect(parsed.assumptions).toHaveLength(report.assumptions.length);
    expect(parsed.warnings).toHaveLength(report.warnings.length);
  });
});

describe("reportToMarkdown", () => {
  it("is deterministic for the same report", () => {
    expect(reportToMarkdown(report)).toBe(reportToMarkdown(report));
  });

  it("leads with the source → target header and the mode/status line", () => {
    const md = reportToMarkdown(report);
    expect(md).toContain(`**${report.source.filename}**`);
    expect(md).toContain(`\`${report.source.format_id}\``);
    expect(md).toContain(`\`${report.target.format_id}\``);
    expect(md).toContain(`Mode \`${report.mode}\``);
  });

  it("renders every outcome section that has rows, in outcome-first order", () => {
    const md = reportToMarkdown(report);
    const assumed = md.indexOf("## Assumed");
    const lost = md.indexOf("## Lost");
    const warned = md.indexOf("## Warned");
    const kept = md.indexOf("## Kept");
    // The worked fixture has all four outcomes; Assumed must lead and Kept must trail.
    expect(assumed).toBeGreaterThan(-1);
    expect(kept).toBeGreaterThan(-1);
    expect(assumed).toBeLessThan(lost);
    expect(lost).toBeLessThan(warned);
    expect(warned).toBeLessThan(kept);
  });

  it("renders every row with the canonical path and verbatim reasons", () => {
    const md = reportToMarkdown(report);
    for (const entry of report.removed) {
      expect(md).toContain(entry.reason);
      expect(md).toContain(`\`${entry.path}\``);
    }
    for (const warning of report.warnings) {
      expect(md).toContain(warning.message);
      expect(md).toContain(warning.code);
    }
    for (const assumption of report.assumptions) {
      expect(md).toContain(assumption.description);
      expect(md).toContain(`**${assumption.id}**`);
    }
    for (const entry of report.preserved) {
      expect(md).toContain(`\`${entry.path}\``);
    }
  });

  it("states what an assumption supplied, from the report's own join", () => {
    const md = reportToMarkdown(report);
    for (const supplied of report.supplied) {
      expect(md).toContain(`\`${supplied.path}\``);
    }
  });

  it("omits empty outcome sections (the affirmative zero accounting lives in the chips)", () => {
    const lossless: ConversionReport = { ...report, removed: [], assumptions: [], supplied: [], warnings: [] };
    const md = reportToMarkdown(lossless);
    expect(md).not.toContain("## Assumed");
    expect(md).not.toContain("## Lost");
    expect(md).not.toContain("## Warned");
    expect(md).toContain("## Kept");
  });
});
