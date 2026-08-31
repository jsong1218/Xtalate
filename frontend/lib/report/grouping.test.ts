import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversionReport } from "./types";
import completedReport from "@/components/report/__fixtures__/conversion.completed.json";
import {
  buildReportRows,
  canonicalCategory,
  countByFilter,
  DEFAULT_GROUPING_MODE,
  filterRows,
  groupRowsByCategory,
  groupRowsByOutcome,
  groupByKey,
  loadGroupingMode,
  outcomeOf,
  OUTCOME_ORDER,
  REPORT_GROUPING_STORAGE_KEY,
  saveGroupingMode,
  shouldCollapse,
} from "./grouping";

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

// --- Outcome-first report grouping (UI redesign S3, D245) --------------------------------------

const report = completedReport as unknown as ConversionReport;

/** A report whose four arrays hold one entry each, for order/structure assertions. */
const oneOfEach: ConversionReport = {
  ...report,
  preserved: [{ path: "atoms.positions", detail: null }],
  removed: [{ path: "dynamics.forces", reason: "dropped", detail: null }],
  supplied: [],
  assumptions: [
    {
      id: "A1",
      scenario: "missing_lattice",
      choice: "bounding_box",
      parameters: { padding_ang: 5 },
      origin: "user" as const,
      description: "A box was built.",
    },
  ],
  warnings: [{ code: "FORMAT_LOSSY_NOTE", message: "note", source: "capability" as const }],
};

describe("outcomeOf / canonicalCategory", () => {
  it("maps every row kind to its outcome", () => {
    expect(outcomeOf("preserved")).toBe("kept");
    expect(outcomeOf("removed")).toBe("lost");
    expect(outcomeOf("assumed")).toBe("assumed");
    expect(outcomeOf("warned")).toBe("warned");
  });

  it("derives the canonical category from the top-level path segment", () => {
    expect(canonicalCategory("dynamics.forces")).toBe("dynamics");
    expect(canonicalCategory("user_metadata.custom_per_frame['extxyz:config_type']")).toBe(
      "user_metadata",
    );
    expect(canonicalCategory("atoms")).toBe("atoms");
  });
});

describe("buildReportRows (the no-loss view model)", () => {
  it("yields exactly one row per preserved / removed / assumption / warning entry", () => {
    const rows = buildReportRows(report);
    expect(rows).toHaveLength(
      report.preserved.length + report.removed.length + report.assumptions.length + report.warnings.length,
    );
    // The kinds are the four arrays, counted correctly.
    expect(rows.filter((r) => r.kind === "preserved")).toHaveLength(report.preserved.length);
    expect(rows.filter((r) => r.kind === "removed")).toHaveLength(report.removed.length);
    expect(rows.filter((r) => r.kind === "assumed")).toHaveLength(report.assumptions.length);
    expect(rows.filter((r) => r.kind === "warned")).toHaveLength(report.warnings.length);
  });

  it("assigns each row the outcome its kind belongs to", () => {
    for (const row of buildReportRows(report)) {
      expect(row.outcome).toBe(outcomeOf(row.kind));
    }
  });

  it("buckets an assumption by the category of the field it supplied", () => {
    // A1 (frame_selection) supplies nothing in the worked fixture; A2 (missing_lattice) supplies
    // cell.lattice_vectors + cell.pbc — so A2 lands in `cell`, A1 in the recovery bucket.
    const rows = buildReportRows(report);
    const a2 = rows.find((r) => r.kind === "assumed" && (r.entry as { id: string }).id === "A2");
    expect(a2?.category).toBe("cell");
    const a1 = rows.find((r) => r.kind === "assumed" && (r.entry as { id: string }).id === "A1");
    expect(a1?.category).toBe("recovery");
  });

  it("keeps one row per duplicate warning code (warnings are never collapsed in the model)", () => {
    const flood: ConversionReport = {
      ...report,
      warnings: [
        { code: "FORMAT_LOSSY_NOTE", message: "one", source: "capability" as const },
        { code: "FORMAT_LOSSY_NOTE", message: "two", source: "capability" as const },
      ],
    };
    const rows = buildReportRows(flood);
    expect(rows.filter((r) => r.kind === "warned")).toHaveLength(2);
    expect(new Set(rows.filter((r) => r.kind === "warned").map((r) => r.id)).size).toBe(2);
  });
});

describe("groupRowsByOutcome", () => {
  it("orders sections Assumed → Lost → Warned → Kept, dropping empty buckets", () => {
    const sections = groupRowsByOutcome(buildReportRows(oneOfEach));
    expect(sections.map((s) => s.key)).toEqual(["assumed", "lost", "warned", "kept"]);
    expect(sections.map((s) => s.label)).toEqual(["Assumed", "Lost", "Warned", "Kept"]);
  });

  it("respects the fixed OUTCOME_ORDER regardless of report-array order", () => {
    // The report model lists preserved first; outcome-first must still lead with Assumed.
    const sections = groupRowsByOutcome(buildReportRows(oneOfEach));
    expect(sections[0].key).toBe(OUTCOME_ORDER[0]);
    expect(OUTCOME_ORDER[0]).toBe("assumed");
  });

  it("returns an empty list for an empty report", () => {
    const empty: ConversionReport = { ...oneOfEach, preserved: [], removed: [], assumptions: [], warnings: [] };
    expect(groupRowsByOutcome(buildReportRows(empty))).toEqual([]);
  });
});

describe("groupRowsByCategory", () => {
  it("groups rows by canonical category in first-seen order", () => {
    const sections = groupRowsByCategory(buildReportRows(oneOfEach));
    // Row order in the model: preserved (atoms) → removed (dynamics) → assumed (cell via supplied)…
    // here A1 supplies nothing → recovery. First-seen: atoms, dynamics, recovery, warnings.
    expect(sections.map((s) => s.key)).toEqual(["atoms", "dynamics", "recovery", "warnings"]);
    expect(sections.map((s) => s.label)).toEqual(["Atoms", "Dynamics", "Recovery", "Warnings"]);
  });

  it("mixes outcomes inside one category (the point of the view)", () => {
    const mixed: ConversionReport = {
      ...oneOfEach,
      preserved: [{ path: "dynamics.forces", detail: null }],
      removed: [{ path: "dynamics.velocities", reason: "dropped", detail: null }],
      assumptions: [],
      warnings: [],
      supplied: [],
    };
    const sections = groupRowsByCategory(buildReportRows(mixed));
    const dynamics = sections.find((s) => s.key === "dynamics")!;
    expect(dynamics.rows.map((r) => r.kind).sort()).toEqual(["preserved", "removed"]);
  });
});

describe("filterRows / countByFilter", () => {
  it("keeps everything for 'all' and narrows to one outcome otherwise", () => {
    const rows = buildReportRows(oneOfEach);
    expect(filterRows(rows, "all")).toHaveLength(4);
    expect(filterRows(rows, "lost").map((r) => r.outcome)).toEqual(["lost"]);
    expect(filterRows(rows, "assumed").map((r) => r.kind)).toEqual(["assumed"]);
  });

  it("counts every outcome for the live chips", () => {
    const counts = countByFilter(buildReportRows(oneOfEach));
    expect(counts).toEqual({ all: 4, kept: 1, lost: 1, assumed: 1, warned: 1 });
  });
});

describe("loadGroupingMode / saveGroupingMode (persisted choice)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("defaults to outcome-first when nothing is stored", () => {
    expect(loadGroupingMode()).toBe(DEFAULT_GROUPING_MODE);
    expect(DEFAULT_GROUPING_MODE).toBe("outcome");
  });

  it("round-trips a saved choice through localStorage", () => {
    saveGroupingMode("category");
    expect(window.localStorage.getItem(REPORT_GROUPING_STORAGE_KEY)).toBe("category");
    expect(loadGroupingMode()).toBe("category");
    saveGroupingMode("outcome");
    expect(loadGroupingMode()).toBe("outcome");
  });

  it("falls back to the default on a garbage value and on storage failure", () => {
    window.localStorage.setItem(REPORT_GROUPING_STORAGE_KEY, "by-alphabet");
    expect(loadGroupingMode()).toBe("outcome");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("privacy mode");
    });
    expect(loadGroupingMode()).toBe("outcome");
  });

  it("never throws when saving is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => saveGroupingMode("category")).not.toThrow();
  });
});
