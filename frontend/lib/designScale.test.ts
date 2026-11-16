import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The design-scale lint (redesign §9). Spacing is 4/8/12/16/24/32 (Tailwind 1/2/3/4/6/8), radius is
 * 2/4/6 (`rounded-sm` / `rounded` / `rounded-md`) — so the classes below must not appear in
 * `app/` or `components/` (type is not linted here):
 *   - `rounded-lg|xl|2xl|3xl` (any side variant), and `rounded-full` except on dots/progress bars
 *     (a line that also sizes the element at h-1…h-3 or h-[1.1em]);
 *   - `p-5`, `p-7`, `gap-5`, `gap-7` and their axis/side variants;
 *   - arbitrary pixel values `[Npx]`.
 * Like `lib/bundleSplit.test.ts` this is a source-level walk, not a runtime check.
 *
 * KNOWN_DEBT lists the files that still carry pre-redesign classes. Every later slice rebuilds some
 * of them and must delete the entries it fixes (a listed file that is now clean fails this test), so
 * the list only shrinks; it is empty at S6.
 */
const ROOT = process.cwd();
const SCAN_DIRS = ["app", "components"];

const RADIUS_RE = /\brounded-(?:[a-z]{1,2}-)?(?:lg|xl|2xl|3xl)\b/;
const RADIUS_FULL_RE = /\brounded-full\b/;
const DOT_RE = /\bh-(?:1|1\.5|2|2\.5|3)(?![\d.])|h-\[1\.1em\]/;
const SPACING_RE =
  /\b(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|gap-x|gap-y|space-x|space-y)-(?:5|7)\b/;
const ARBITRARY_PX_RE = /\[\d+px\]/;

type Rule = "radius" | "radiusFull" | "spacing" | "arbitraryPx";

const KNOWN_DEBT: Record<Rule, string[]> = {
  radius: [
    "app/f/[file_id]/analysis/page.tsx",
    "components/AnalysisResults.tsx",
    "components/DownloadPanel.tsx",
    "components/ErrorEnvelope.tsx",
    "components/Provenance.tsx",
    "components/TargetPicker.tsx",
    "components/command/CommandPalette.tsx",
    "components/history/HistoryTableView.tsx",
    "components/presets/PresetManager.tsx",
    "components/recovery/DecisionCard.tsx",
    "components/recovery/RecoveryStep.tsx",
    "components/repair/RepairPicker.tsx",
    "components/report/ConversionReportPanel.tsx",
    "components/report/RefusalPanel.tsx",
    "components/report/ValidationReportPanel.tsx",
    "components/shell/DemoPrivacyGate.tsx",
    "components/upload/UploadDropzone.tsx",
    "components/workspace/ConversionJob.tsx",
    "components/workspace/ConversionRecord.tsx",
  ],
  radiusFull: [
    "components/JobPhase.tsx",
    "components/report/ReportToolbar.tsx",
    "components/report/SummaryChips.tsx",
    "components/shell/Inspector.tsx",
    "components/shell/SourceRail.tsx",
  ],
  spacing: [
    "app/f/[file_id]/analysis/page.tsx",
    "app/f/[file_id]/layout.tsx",
    "app/formats/page.tsx",
    "components/TargetPicker.tsx",
    "components/formats/FormatDetail.tsx",
    "components/formats/FormatGuidePanel.tsx",
    "components/recovery/RecoveryStep.tsx",
    "components/upload/LandingUpload.tsx",
  ],
  arbitraryPx: [],
};

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const abs = join(dir, entry);
    if (entry === "node_modules") continue;
    if (statSync(abs).isDirectory()) {
      out.push(...sourceFiles(abs));
    } else if (/\.tsx?$/.test(entry) && !/\.(test|spec)\.tsx?$/.test(entry)) {
      out.push(abs);
    }
  }
  return out;
}

function violates(rule: Rule, source: string): boolean {
  const lines = source.split("\n");
  switch (rule) {
    case "radius":
      return RADIUS_RE.test(source);
    case "radiusFull":
      return lines.some((l) => RADIUS_FULL_RE.test(l) && !DOT_RE.test(l));
    case "spacing":
      return SPACING_RE.test(source);
    case "arbitraryPx":
      return ARBITRARY_PX_RE.test(source);
  }
}

const files = SCAN_DIRS.flatMap((d) => sourceFiles(join(ROOT, d))).map((abs) => ({
  rel: relative(ROOT, abs).split("\\").join("/"),
  source: readFileSync(abs, "utf8"),
}));

describe("design scale (redesign §9)", () => {
  it.each(Object.keys(KNOWN_DEBT) as Rule[])("no new %s violations outside KNOWN_DEBT", (rule) => {
    const debt = new Set(KNOWN_DEBT[rule]);
    const offenders = files.filter((f) => violates(rule, f.source) && !debt.has(f.rel)).map((f) => f.rel);
    expect(offenders, `fix these or (never) add them to KNOWN_DEBT.${rule}`).toEqual([]);
  });

  it.each(Object.keys(KNOWN_DEBT) as Rule[])("KNOWN_DEBT.%s only shrinks", (rule) => {
    const stale = KNOWN_DEBT[rule].filter((rel) => {
      const f = files.find((x) => x.rel === rel);
      return !f || !violates(rule, f.source);
    });
    expect(stale, `these files are clean now — remove them from KNOWN_DEBT.${rule}`).toEqual([]);
  });
});
