import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CHOICE_LABELS,
  CUSTOM_CATEGORY_LABELS,
  PATH_LABELS,
  SCENARIO_LABELS,
  labelForChoice,
  labelForPath,
} from "./mapping";

/**
 * The mapping-coverage lint (MASTER_SPEC Part 7 §3.3; Part 8 §1.1 frontend row).
 *
 * It reads the committed `docs/vocabulary.json` — exported from the engine's own registries by
 * `python -m backend.vocabulary` — and fails if any scenario code or canonical path the engine can
 * produce lacks a plain-language entry in `mapping.ts`. So removing a scenario from the mapping
 * constant, or the engine gaining a new one (including via a plugin), fails CI here rather than
 * showing a raw machine code on screen.
 */
// Resolved from the Vitest working directory (the `frontend/` project root) so it points at the
// committed `docs/vocabulary.json` regardless of how the test module URL is rewritten by the
// transform. This reads the same artifact the backend exports (`python -m backend.vocabulary`).
const vocabularyPath = resolve(process.cwd(), "..", "docs", "vocabulary.json");
const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf-8")) as {
  scenario_codes: string[];
  choice_codes: Record<string, string[]>;
  scenario_resolution_order: string[];
  canonical_paths: string[];
  custom_path_categories: string[];
};

/** Every `[scenario, choice]` the engine can offer, flattened for the per-choice coverage lint. */
const choicePairs: [string, string][] = Object.entries(vocabulary.choice_codes).flatMap(
  ([scenario, choices]) => choices.map((choice): [string, string] => [scenario, choice]),
);

describe("plain-language mapping coverage", () => {
  it("has a sanity floor of vocabulary to check", () => {
    expect(vocabulary.scenario_codes.length).toBeGreaterThan(0);
    expect(vocabulary.canonical_paths.length).toBeGreaterThan(0);
    expect(vocabulary.custom_path_categories.length).toBeGreaterThan(0);
  });

  it.each(vocabulary.scenario_codes)("scenario code %s has a plain-language label", (code) => {
    expect(SCENARIO_LABELS, `add "${code}" to SCENARIO_LABELS in mapping.ts`).toHaveProperty(code);
  });

  it.each(choicePairs)("choice %s / %s has a plain-language label", (scenario, choice) => {
    expect(
      CHOICE_LABELS[scenario],
      `add the "${scenario}" scenario to CHOICE_LABELS in mapping.ts`,
    ).toHaveProperty(choice);
    // The resolver never reaches its raw-code fallback for a known choice — it returns the label.
    expect(labelForChoice(scenario, choice).label).not.toBe(choice);
  });

  it.each(vocabulary.canonical_paths)("canonical path %s has a plain-language label", (path) => {
    expect(PATH_LABELS, `add "${path}" to PATH_LABELS in mapping.ts`).toHaveProperty(path);
  });

  it.each(vocabulary.custom_path_categories)("custom category %s has a label", (prefix) => {
    expect(CUSTOM_CATEGORY_LABELS, `add "${prefix}" to CUSTOM_CATEGORY_LABELS`).toHaveProperty(
      prefix,
    );
  });

  it("resolves a concrete custom_* path to its category label plus the key", () => {
    const resolved = labelForPath("user_metadata.custom_global['stress_eV']");
    expect(resolved.label).toContain("Custom global value");
    expect(resolved.label).toContain("stress_eV");
  });
});
