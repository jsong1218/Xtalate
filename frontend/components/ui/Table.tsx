import type { ReactNode } from "react";

/**
 * Table primitives for the field tables (redesign §5, §9): pre-flight predictions, the report ledger,
 * the batch results. Plain `<table>` semantics (`scope="col"` headers, optional caption) with three
 * cell kinds — text, numeric (right-aligned mono, tabular numerals) and status (a `--cb-*` dot plus
 * the plain-language word). The status *word* carries the meaning; the dot is decorative, so colour
 * is never the only signal (Part 7 §4).
 */
export type StatusTone = "preserve" | "assumption" | "removed" | "warning" | "fail" | "repair" | "neutral";

const TONE_TEXT: Record<StatusTone, string> = {
  preserve: "text-cb-preserve",
  assumption: "text-cb-assumption",
  removed: "text-cb-removed",
  warning: "text-cb-warning",
  fail: "text-cb-fail",
  repair: "text-cb-repair",
  neutral: "text-muted",
};
const TONE_DOT: Record<StatusTone, string> = {
  preserve: "bg-cb-preserve",
  assumption: "bg-cb-assumption",
  removed: "bg-cb-removed",
  warning: "bg-cb-warning",
  fail: "bg-cb-fail",
  repair: "bg-cb-repair",
  neutral: "bg-line-strong",
};

function cx(...parts: Array<string | undefined | false>): string {
  return parts.filter(Boolean).join(" ");
}

export function Table({ children, caption, className }: { children: ReactNode; caption?: string; className?: string }) {
  return (
    <table className={cx("w-full border-collapse text-sm", className)}>
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      {children}
    </table>
  );
}

export function Th({ children, numeric, className }: { children: ReactNode; numeric?: boolean; className?: string }) {
  return (
    <th
      scope="col"
      className={cx(
        "border-b border-line px-2 py-1 text-xs2 font-medium uppercase tracking-wide text-faint",
        numeric ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({ children, numeric, className }: { children: ReactNode; numeric?: boolean; className?: string }) {
  return (
    <td
      className={cx(
        "border-b border-line-soft px-2 py-1 align-top",
        numeric ? "text-right font-mono tabular-nums text-strong" : "text-left text-body",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function StatusCell({ tone, children, className }: { tone: StatusTone; children: ReactNode; className?: string }) {
  return (
    <td className={cx("border-b border-line-soft px-2 py-1 align-top", TONE_TEXT[tone], className)}>
      <span className="inline-flex items-center gap-2">
        <span aria-hidden="true" className={cx("inline-block h-2 w-2 rounded-full", TONE_DOT[tone])} />
        {children}
      </span>
    </td>
  );
}
