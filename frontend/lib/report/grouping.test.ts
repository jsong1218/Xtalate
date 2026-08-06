import { describe, expect, it } from "vitest";
import { groupByKey, shouldCollapse } from "./grouping";

/**
 * The pure grouping logic behind S4's collapsible report groups. Two guarantees the panel leans on:
 * groups appear in **first-seen key order** (so the rendered order is stable and matches the report
 * arrays), and `shouldCollapse` is true **only when a key actually repeats** — a section with no
 * repetition stays a flat list, so the common single-warning case is never dressed up as an
 * accordion.
 */
describe("groupByKey", () => {
  it("groups items sharing a key, preserving first-seen key order", () => {
    const items = [
      { code: "A", n: 1 },
      { code: "B", n: 2 },
      { code: "A", n: 3 },
      { code: "B", n: 4 },
      { code: "A", n: 5 },
    ];
    const groups = groupByKey(items, (i) => i.code);
    expect(groups.map((g) => g.key)).toEqual(["A", "B"]);
    expect(groups[0].items.map((i) => i.n)).toEqual([1, 3, 5]);
    expect(groups[1].items.map((i) => i.n)).toEqual([2, 4]);
  });

  it("preserves within-group order as encountered", () => {
    const items = [
      { code: "X", n: 10 },
      { code: "X", n: 20 },
    ];
    const groups = groupByKey(items, (i) => i.code);
    expect(groups).toHaveLength(1);
    expect(groups[0].items.map((i) => i.n)).toEqual([10, 20]);
  });

  it("returns one singleton group per item when every key is distinct", () => {
    const items = [{ code: "A" }, { code: "B" }, { code: "C" }];
    const groups = groupByKey(items, (i) => i.code);
    expect(groups.map((g) => g.key)).toEqual(["A", "B", "C"]);
    expect(groups.every((g) => g.items.length === 1)).toBe(true);
  });

  it("returns an empty array for no items", () => {
    expect(groupByKey([], () => "k")).toEqual([]);
  });
});

describe("shouldCollapse", () => {
  it("is false when every group is a singleton (no repetition to tame)", () => {
    const groups = groupByKey([{ c: "A" }, { c: "B" }], (i) => i.c);
    expect(shouldCollapse(groups)).toBe(false);
  });

  it("is true when any group holds two or more items", () => {
    const groups = groupByKey([{ c: "A" }, { c: "A" }, { c: "B" }], (i) => i.c);
    expect(shouldCollapse(groups)).toBe(true);
  });

  it("is false for an empty section", () => {
    expect(shouldCollapse([])).toBe(false);
  });
});
