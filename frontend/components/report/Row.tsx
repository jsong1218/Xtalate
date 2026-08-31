import type { ReactNode } from "react";
import { LossIcon, type LossKind } from "@/components/loss/icons";
import { DataValue } from "@/components/ui/DataValue";

/**
 * One presence/outcome row — the shared atom every report section is a list of (MASTER_SPEC
 * Part 7 §4.2). A row is `icon + primary label + optional detail`, with a `children` slot for the
 * one piece of section-specific text a row sometimes carries: the **verbatim `reason`** on a
 * Removed row, the field list under an Assumption, the `code` badge + message on a Warning. The
 * icon's meaning comes from {@link LossKind} and is never color-only — `LossIcon` carries the §4
 * `aria-label` — so a row reads correctly to assistive tech and under color-vision deficiency.
 *
 * The label is a `ReactNode`, not a string, because callers resolve the plain-language label
 * through `lib/mapping.ts` (never inline) and pass the result in; this component does no mapping of
 * its own. Rendered as an `<li>`: sections wrap rows in a `<ul>` so counts are structural.
 */
export function Row({
  kind,
  label,
  detail,
  testId,
  children,
  id,
}: {
  kind: LossKind;
  label: ReactNode;
  /** Secondary quantitative line, e.g. "9 of 10 frames dropped". */
  detail?: string | null;
  /** Stable hook so a section can assert its row count against the report array (fixture-first). */
  testId?: string;
  children?: ReactNode;
  /** Fragment anchor (v1.6 M60-S3): lets an Assumption row be the landing target of a link. */
  id?: string;
}) {
  return (
    <li
      id={id}
      data-testid={testId}
      className="flex scroll-mt-24 gap-2.5 px-3 py-2"
    >
      <LossIcon kind={kind} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="text-sm font-medium text-strong">{label}</div>
        {/* The source value, in mono — the S1 precision-instrument rule applied to every report
            row (UI redesign S3, D245): a value is always visually a value, and it is never
            collapsed away. */}
        {detail ? (
          <div className="text-sm">
            <DataValue>{detail}</DataValue>
          </div>
        ) : null}
        {children}
      </div>
    </li>
  );
}
