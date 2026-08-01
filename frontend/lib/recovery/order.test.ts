import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { RECOVERY_RESOLUTION_ORDER, orderedScenarios } from "./order";
import type { AwaitingScenario } from "@/lib/report/types";

/**
 * The recovery resolution order the wizard renders in (Part 4 §3.3; v0.7 review, F4) must match the
 * engine's own, published in `docs/vocabulary.json` — replacing the old hand-copied `DEP_ORDER` with
 * a constant a test keeps in lockstep. This reads the same artifact the mapping-coverage lint does.
 */
const vocabularyPath = resolve(process.cwd(), "..", "docs", "vocabulary.json");
const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf-8")) as {
  scenario_resolution_order: string[];
};

const scenario = (code: string): AwaitingScenario => ({
  scenario: code,
  path: null,
  detail: null,
  options: [],
});

describe("recovery resolution order", () => {
  it("matches the engine's exported scenario_resolution_order exactly", () => {
    expect([...RECOVERY_RESOLUTION_ORDER]).toEqual(vocabulary.scenario_resolution_order);
  });

  it("sorts a parse-time scenario ahead of a conversion-time one (the F4 case)", () => {
    // A mixed pause arriving in the wrong order: missing_lattice (conversion-time) before
    // missing_species (parse-time). The old tail-sorting copy rendered species last; this puts it first.
    const ordered = orderedScenarios([scenario("missing_lattice"), scenario("missing_species")]);
    expect(ordered.map((s) => s.scenario)).toEqual(["missing_species", "missing_lattice"]);
  });

  it("orders frame_selection before missing_lattice regardless of arrival order", () => {
    const ordered = orderedScenarios([scenario("missing_lattice"), scenario("frame_selection")]);
    expect(ordered.map((s) => s.scenario)).toEqual(["frame_selection", "missing_lattice"]);
  });

  it("keeps an unknown (plugin) scenario after the known ones, in block order", () => {
    const ordered = orderedScenarios([
      scenario("plugin_scenario"),
      scenario("frame_selection"),
    ]);
    expect(ordered.map((s) => s.scenario)).toEqual(["frame_selection", "plugin_scenario"]);
  });
});
