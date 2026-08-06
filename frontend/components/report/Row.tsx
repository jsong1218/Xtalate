import type { ReactNode } from "react";
import { LossIcon, type LossKind } from "@/components/loss/icons";

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
}: {
  kind: LossKind;
  label: ReactNode;
  /** Secondary quantitative line, e.g. "9 of 10 frames dropped". */
  detail?: string | null;
  /** Stable hook so a section can assert its row count against the report array (fixture-first). */
  testId?: string;
  children?: ReactNode;
}) {
  return (
    <li data-testid={testId} className="flex gap-2.5 px-3 py-2">
      <LossIcon kind={kind} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="text-sm font-medium text-strong">{label}</div>
        {detail ? <div className="text-sm text-muted">{detail}</div> : null}
        {children}
      </div>
    </li>
  );
}
