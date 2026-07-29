import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { WHY_THIS_MATTERS } from "./why";

/**
 * The "Why does this matter?" coverage lint (MASTER_SPEC Part 7 §3.3; Part 8 §1.1 frontend row) —
 * the same discipline as `lib/mapping.coverage.test.ts`, applied to the non-expert content layer.
 *
 * It reads the committed `docs/vocabulary.json` — exported from the engine's own registries by
 * `python -m backend.vocabulary` — and fails if any scenario code the engine can pause on lacks
 * disclosure copy in `why.ts`. So the engine gaining a new scenario (including via a plugin) fails
 * CI here rather than showing a card with no "why does this matter?" for a non-expert to read.
 *
 * The `frame_selection` and `missing_lattice` copy is the flagship's own and un-cuttable; the lint
 * additionally pins those two so a breadth cut can never quietly take them.
 */
const vocabularyPath = resolve(process.cwd(), "..", "docs", "vocabulary.json");
const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf-8")) as {
  scenario_codes: string[];
};

describe("why-this-matters coverage", () => {
  it("has a sanity floor of scenario codes to check", () => {
    expect(vocabulary.scenario_codes.length).toBeGreaterThan(0);
  });

  it.each(vocabulary.scenario_codes)("scenario code %s has disclosure copy", (code) => {
    expect(WHY_THIS_MATTERS, `add "${code}" to WHY_THIS_MATTERS in why.ts`).toHaveProperty(code);
    const entry = WHY_THIS_MATTERS[code];
    expect(entry.question.trim(), `"${code}" needs a disclosure prompt`).not.toBe("");
    expect(entry.stakes.length, `"${code}" needs at least one stakes paragraph`).toBeGreaterThan(0);
    for (const paragraph of entry.stakes) {
      expect(paragraph.trim(), `"${code}" has an empty stakes paragraph`).not.toBe("");
    }
  });

  it.each(["frame_selection", "missing_lattice"])(
    "keeps the un-cuttable flagship copy for %s",
    (code) => {
      // The flagship worked example turns on exactly these two decisions; a breadth cut may thin the
      // other scenarios' prose but must never remove these.
      expect(WHY_THIS_MATTERS).toHaveProperty(code);
      expect(WHY_THIS_MATTERS[code].stakes.length).toBeGreaterThan(0);
    },
  );
});
