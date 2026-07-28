/**
 * The recovery-choice logic behind the Recovery Workflow UI (MASTER_SPEC Part 6 §3.2, Part 7 §3;
 * slice M31-S1).
 *
 * This module owns the wizard's *data*, kept free of React so the load-bearing invariants — the
 * exact `{scenario: {choice, parameters}}` body the engine validated in v0.5, and the completeness
 * rules that gate the preview/submit — are provable in isolation. The card components read and write
 * a {@link WizardState}; this file turns it into the resume body and answers "is this choice ready?".
 *
 * Parameter validity is keyed on the engine's own stable parameter names (`padding_ang`, `lattice`,
 * …), the same tokens `backend/jobs/recovery.py::_PARAMETERS_SCHEMA` advertises — so the client and
 * the engine agree on what each field is without the client re-deriving any scientific rule (P2). A
 * parameter the client does not recognise is treated as "present is enough": a future plugin
 * scenario gets a generic-but-functional gate rather than a card that can never complete (P6).
 */

import type { AwaitingScenario, RecoveryOption } from "@/lib/report/types";
import type { RecoveryDecision } from "@/lib/api/queries";

/** scenario code → the decision the user has made for it so far. */
export type WizardState = Record<string, RecoveryDecision>;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function is3x3(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every((row) => Array.isArray(row) && row.length === 3 && row.every(isFiniteNumber))
  );
}

/**
 * Whether a single parameter's value is valid, keyed by the engine's parameter name. Unknown names
 * fall back to "any present, non-empty value" so an unrecognised (e.g. plugin-supplied) schema still
 * gates sensibly instead of blocking forever.
 */
export function isParamValid(name: string, value: unknown): boolean {
  switch (name) {
    case "padding_ang":
      return isFiniteNumber(value) && value >= 0;
    case "temperature_K":
      return isFiniteNumber(value) && value > 0;
    case "frame_index":
      return isInteger(value) && value >= 0;
    case "seed":
      return isInteger(value);
    case "lattice":
      return is3x3(value);
    case "masses":
      return Array.isArray(value) && value.length > 0 && value.every(isFiniteNumber);
    case "symbols":
      return (
        Array.isArray(value) &&
        value.length > 0 &&
        value.every((s) => typeof s === "string" && s.trim().length > 0)
      );
    case "reference":
      return typeof value === "string" && value.length > 0;
    default:
      return value !== undefined && value !== null && value !== "";
  }
}

/**
 * Whether a chosen option has every parameter it advertises filled with a valid value. A choice with
 * no `parameters_schema` (`first`, `last`, `zero_init`, …) is complete the moment it is selected.
 */
export function isOptionComplete(option: RecoveryOption, parameters: Record<string, unknown>): boolean {
  const schema = option.parameters_schema ?? {};
  return Object.keys(schema).every((name) => isParamValid(name, parameters[name]));
}

/** The `POST …/recovery` body: exactly the selected `{scenario: {choice, parameters}}` map. */
export function buildRecoveryBody(state: WizardState): Record<string, RecoveryDecision> {
  const body: Record<string, RecoveryDecision> = {};
  for (const [scenario, decision] of Object.entries(state)) {
    if (decision.choice) body[scenario] = decision;
  }
  return body;
}

/**
 * Whether every unresolved scenario has a selected, fully-parameterised choice — the gate for
 * previewing (recovery is all-or-nothing) and for submitting. Uses each scenario's own `options` so
 * an option the engine never offered can never be considered complete.
 */
export function isWizardComplete(scenarios: AwaitingScenario[], state: WizardState): boolean {
  return scenarios.every((scenario) => {
    const decision = state[scenario.scenario];
    if (!decision?.choice) return false;
    const option = scenario.options.find((o) => o.choice === decision.choice);
    return option !== undefined && isOptionComplete(option, decision.parameters);
  });
}
