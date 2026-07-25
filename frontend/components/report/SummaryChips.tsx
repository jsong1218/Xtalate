import { LOSS_GLYPHS, LossIcon, type LossKind } from "@/components/loss/icons";
import type { ConversionReport } from "@/lib/report/types";

/**
 * The at-a-glance count chips for a Conversion Report (MASTER_SPEC Part 7 §4.1) — preserved,
 * removed, assumptions, warnings. Two rules make these honest:
 *
 *  1. **Every category is always shown, labeled, even at zero** — never an unlabeled blank. A
 *     clean conversion renders "✓ 0 fields removed · ✓ 0 assumptions", not an empty space a reader
 *     has to interpret. The count is always beside a word.
 *  2. **A zero in a *loss* category is good news, so it renders affirmatively** — green ✓, the
 *     `preserved` styling — rather than in its alarm color. A red "0 removed" would misread the
 *     outcome; the alarm color appears only when there is something to be alarmed about (count > 0).
 *
 * These chips summarize; the panel sections below them carry the per-field detail. Counts come
 * straight off the report arrays — the client never recomputes loss (Part 7 §2).
 */

interface ChipModel {
  count: number;
  singular: string;
  plural: string;
  /** The category's own §4 meaning; used when `count > 0`. */
  kind: LossKind;
}

function Chip({ count, singular, plural, kind }: ChipModel) {
  // A zero loss-count is affirmative: show the calm green ✓, not the category's alarm color.
  const affirmative = count === 0 && kind !== "preserved";
  const shownKind: LossKind = affirmative ? "preserved" : kind;
  const spec = LOSS_GLYPHS[shownKind];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1">
      <LossIcon kind={shownKind} />
      <span className={`text-sm font-medium ${spec.color}`}>
        {count} {count === 1 ? singular : plural}
      </span>
    </span>
  );
}

export function SummaryChips({ report }: { report: ConversionReport }) {
  const chips: ChipModel[] = [
    {
      count: report.preserved.length,
      singular: "field preserved",
      plural: "fields preserved",
      kind: "preserved",
    },
    {
      count: report.removed.length,
      singular: "field removed",
      plural: "fields removed",
      kind: "removed",
    },
    {
      count: report.assumptions.length,
      singular: "assumption",
      plural: "assumptions",
      kind: "assumption",
    },
    { count: report.warnings.length, singular: "warning", plural: "warnings", kind: "warning" },
  ];
  return (
    <div className="flex flex-wrap gap-2" aria-label="Conversion summary">
      {chips.map((chip) => (
        <Chip key={chip.singular} {...chip} />
      ))}
    </div>
  );
}
