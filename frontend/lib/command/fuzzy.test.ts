import { describe, expect, it } from "vitest";
import { fuzzyMatch, fuzzySearch, type CommandCandidate } from "./fuzzy";

/**
 * The in-repo fuzzy matcher (S4, D246) — the no-dependency contract. The palette leans on three
 * properties that must never regress: a query must be a *case-insensitive subsequence* (no match
 * when a char is missing), contiguous/substring matches must outrank scattered ones, and word-start
 * matches must outrank mid-word ones. These tests pin the scoring so a later "improvement" cannot
 * silently reorder the palette in a way no journey would catch.
 */
const noMatch = () => expect(fuzzyMatch("zz", "atoms")).toBeNull();

describe("fuzzyMatch subsequence semantics", () => {
  it("matches a case-insensitive subsequence", () => {
    expect(fuzzyMatch("xyz", "eXtended XYZ")).not.toBeNull();
    expect(fuzzyMatch("xyz", "PXZ")).toBeNull(); // 'y' missing
  });

  it("does not match when a query character is absent or order breaks", () => {
    noMatch();
    expect(fuzzyMatch("atomz", "atoms")).toBeNull();
    expect(fuzzyMatch("om", "atoms")).not.toBeNull(); // subsequence, not prefix
  });

  it("an empty (or blank) query matches nothing scored", () => {
    expect(fuzzyMatch("", "atoms")).toEqual({ score: 0, highlight: [] });
    expect(fuzzyMatch("   ", "atoms")).toEqual({ score: 0, highlight: [] });
  });

  it("a query longer than the target can never match", () => {
    expect(fuzzyMatch("longerthantarget", "pos")).toBeNull();
  });

  it("returns the matched indices for highlighting", () => {
    const m = fuzzyMatch("pos", "POSCAR");
    expect(m).not.toBeNull();
    // 'p','o','s' are the first three letters — consecutive, matched in place.
    expect(m && [...m.highlight]).toEqual([0, 1, 2]);
    expect(m && m.score).toBeGreaterThan(0);
  });
});

describe("fuzzyMatch scoring (what the palette sorts on)", () => {
  it("a contiguous substring outranks the same letters scattered", () => {
    const contig = fuzzyMatch("pos", "POSCAR")!;
    const scattered = fuzzyMatch("pos", "p1-o-s")!;
    expect(contig.score).toBeGreaterThan(scattered.score);
  });

  it("a camelCase / separator word-start adds a boundary bonus over the same run mid-word", () => {
    // Both are contiguous runs of "vec"; the camelCase 'V' in latticeVectors is a word start.
    const camel = fuzzyMatch("vec", "latticeVectors")!;
    const plain = fuzzyMatch("vec", "laveced")!;
    expect(camel.score).toBeGreaterThan(plain.score);
  });

  it("an exact substring nearly always beats even a boundary-rich scattered match", () => {
    // "cell.lattice_vectors" matches "cell" as a clean substring; the scattered competitor shares
    // the letters in order but not contiguously — the substring must rank well above it.
    const substring = fuzzyMatch("cell", "cell.lattice_vectors")!;
    const scattered = fuzzyMatch("cell", "c.extra.e.little.l" )!;
    expect(substring.score).toBeGreaterThan(scattered.score);
  });
});

describe("fuzzySearch ranking", () => {
  const candidates: CommandCandidate<string>[] = [
    { id: "1", label: "POSCAR", search: "POSCAR", payload: "a" },
    { id: "2", label: "CIF", search: "CIF", payload: "b" },
    { id: "3", label: "extXYZ", search: "extXYZ", payload: "c" },
    { id: "4", label: "XDATCAR", search: "XDATCAR", payload: "d" },
  ];

  it("ranks best-first and drops non-matches", () => {
    const ranked = fuzzySearch("pos", candidates);
    expect(ranked.map((r) => r.candidate.id)).toEqual(["1"]);
  });

  it("an empty query returns no results (the palette shows everything by default instead)", () => {
    expect(fuzzySearch("", candidates)).toEqual([]);
  });

  it("picks the exact substring over a scattered subsequence for a shared query", () => {
    const loose: CommandCandidate<string>[] = [
      { id: "sub", label: "POSCAR", search: "POSCAR", payload: "s" },
      { id: "loose", label: "pre-ordered", search: "pre-ordered", payload: "l" },
    ];
    const ranked = fuzzySearch("po", loose);
    expect(ranked[0].candidate.id).toBe("sub");
  });
});