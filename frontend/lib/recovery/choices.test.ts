import { describe, expect, it } from "vitest";
import type { AwaitingScenario, RecoveryOption } from "@/lib/report/types";
import {
  buildRecoveryBody,
  isOptionComplete,
  isParamValid,
  isWizardComplete,
} from "./choices";

/**
 * The pure recovery-choice logic behind the wizard (M31-S1). No React here — this is the exact
 * `{scenario: {choice, parameters}}` body the engine validated in v0.5, plus the completeness rules
 * that gate the preview/submit, tested in isolation so the invariants are provable without a DOM.
 */

const boundingBox: RecoveryOption = {
  choice: "bounding_box",
  parameters_schema: { padding_ang: "float ≥ 0 — padding on each side, Å" },
};
const first: RecoveryOption = { choice: "first" };

describe("isParamValid", () => {
  it("accepts a non-negative padding and rejects a negative or non-numeric one", () => {
    expect(isParamValid("padding_ang", 5)).toBe(true);
    expect(isParamValid("padding_ang", 0)).toBe(true);
    expect(isParamValid("padding_ang", -1)).toBe(false);
    expect(isParamValid("padding_ang", "")).toBe(false);
    expect(isParamValid("padding_ang", undefined)).toBe(false);
  });

  it("requires a 3×3 grid of finite numbers for a lattice", () => {
    const grid = [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ];
    expect(isParamValid("lattice", grid)).toBe(true);
    expect(isParamValid("lattice", [[1, 0, 0]])).toBe(false);
    expect(isParamValid("lattice", [[1, 0, 0], [0, 1, 0], [0, 0, Number.NaN]])).toBe(false);
  });

  it("requires an integer seed but a positive temperature", () => {
    expect(isParamValid("seed", 42)).toBe(true);
    expect(isParamValid("seed", 1.5)).toBe(false);
    expect(isParamValid("temperature_K", 300)).toBe(true);
    expect(isParamValid("temperature_K", 0)).toBe(false);
  });

  it("requires a non-empty file_id reference and a non-empty symbols list", () => {
    expect(isParamValid("reference", "file_abc")).toBe(true);
    expect(isParamValid("reference", "")).toBe(false);
    expect(isParamValid("symbols", ["Na", "Cl"])).toBe(true);
    expect(isParamValid("symbols", [])).toBe(false);
    expect(isParamValid("symbols", ["Na", ""])).toBe(false);
  });
});

describe("isOptionComplete", () => {
  it("a parameter-less choice is complete the moment it is selected", () => {
    expect(isOptionComplete(first, {})).toBe(true);
  });

  it("a parameterised choice needs every advertised parameter valid", () => {
    expect(isOptionComplete(boundingBox, {})).toBe(false);
    expect(isOptionComplete(boundingBox, { padding_ang: 5 })).toBe(true);
    expect(isOptionComplete(boundingBox, { padding_ang: -3 })).toBe(false);
  });
});

const scenario: AwaitingScenario = {
  scenario: "missing_lattice",
  path: "cell.lattice_vectors",
  detail: "target requires cell.lattice_vectors",
  options: [boundingBox, first],
};
const frameScenario: AwaitingScenario = {
  scenario: "frame_selection",
  path: null,
  detail: "2 frames → target holds at most 1",
  options: [{ choice: "first" }, { choice: "last" }],
};

describe("buildRecoveryBody", () => {
  it("emits exactly the {choice, parameters} shape the engine reads, per selected scenario", () => {
    const body = buildRecoveryBody({
      frame_selection: { choice: "last", parameters: {} },
      missing_lattice: { choice: "bounding_box", parameters: { padding_ang: 5 } },
    });
    expect(body).toEqual({
      frame_selection: { choice: "last", parameters: {} },
      missing_lattice: { choice: "bounding_box", parameters: { padding_ang: 5 } },
    });
  });
});

describe("isWizardComplete", () => {
  it("is false until every scenario has a complete choice", () => {
    const scenarios = [frameScenario, scenario];
    expect(isWizardComplete(scenarios, {})).toBe(false);
    expect(
      isWizardComplete(scenarios, { frame_selection: { choice: "last", parameters: {} } }),
    ).toBe(false);
    expect(
      isWizardComplete(scenarios, {
        frame_selection: { choice: "last", parameters: {} },
        missing_lattice: { choice: "bounding_box", parameters: {} },
      }),
    ).toBe(false); // padding still missing
    expect(
      isWizardComplete(scenarios, {
        frame_selection: { choice: "last", parameters: {} },
        missing_lattice: { choice: "bounding_box", parameters: { padding_ang: 5 } },
      }),
    ).toBe(true);
  });
});
