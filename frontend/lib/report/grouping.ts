/**
 * Pure grouping logic for the S4 collapsible report groups (frontend redesign addendum §4.4).
 *
 * The report panels can flood at trajectory scale — dozens of same-code warnings, a long Removed
 * list. Grouping same-typed entries into one expanded-by-default disclosure cuts the wall of text
 * *without* burying anything (the disclosures start open — nothing needs a click to become visible),
 * complementing the engine-side D108 per-frame frame-range collapse.
 *
 * This module owns only the arithmetic — which entries share a key, in what order, and whether the
 * repetition is worth grouping at all. The panel owns the rendering. Keeping it here makes the two
 * guarantees below unit-testable in isolation.
 */

export interface Group<T> {
  /** The shared key (a warning `code`, a canonical category); used as the group's heading + React key. */
  key: string;
  items: T[];
}

/**
 * Bucket `items` by `keyOf`, with groups in **first-seen key order** and each group's items in the
 * order they were encountered. Order is load-bearing: the rendered groups must track the report
 * arrays, never a re-sorted view that would reorder what the engine reported.
 */
export function groupByKey<T>(items: readonly T[], keyOf: (item: T) => string): Group<T>[] {
  const byKey = new Map<string, Group<T>>();
  const order: Group<T>[] = [];
  for (const item of items) {
    const key = keyOf(item);
    let group = byKey.get(key);
    if (group === undefined) {
      group = { key, items: [] };
      byKey.set(key, group);
      order.push(group);
    }
    group.items.push(item);
  }
  return order;
}

/**
 * Whether a section should render as collapsible groups rather than a flat list. True **only when a
 * key repeats** (some group holds ≥ 2 items) — that is the flood grouping exists to tame. A section
 * whose entries are all distinct stays flat, so a single warning is never dressed up as an accordion
 * of one.
 */
export function shouldCollapse<T>(groups: readonly Group<T>[]): boolean {
  return groups.some((group) => group.items.length >= 2);
}
