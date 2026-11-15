import type { ReactNode } from "react";
import { DataValue } from "./DataValue";

/**
 * A horizontal strip of key/value facts (redesign §9): the stage-1 source summary ("POSCAR · 2
 * atoms · 1 frame"), the stage-5 header facts. A `<dl>` so each value is announced with its key;
 * `mono` values go through `DataValue` (tabular numerals), text values stay in the sans.
 */
export interface KeyValueItem {
  key: string;
  value: ReactNode;
  mono?: boolean;
}

export function KeyValueStrip({ items, label, className }: { items: KeyValueItem[]; label?: string; className?: string }) {
  const base = "flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs";
  return (
    <dl aria-label={label} className={className ? `${base} ${className}` : base}>
      {items.map((item) => (
        <div key={item.key} className="flex items-baseline gap-1">
          <dt className="text-faint">{item.key}</dt>
          <dd className={item.mono ? "font-mono tabular-nums text-strong" : "text-body"}>
            {item.mono ? <DataValue>{item.value}</DataValue> : item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
