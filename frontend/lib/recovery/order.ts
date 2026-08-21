/**
 * The engine's recovery resolution order (MASTER_SPEC Part 4 §3.3; v0.7 review, F4).
 *
 * A paused job's `awaiting_recovery` block carries one unresolved scenario per decision the
 * conversion still owes, and the wizard renders a card for each **in the order the engine resolves
 * them** — so a downstream decision (a bounding box computed on a chosen frame) reads below the one
 * it depends on. That order is engine knowledge, not UI knowledge (v0.7 standing rule 3: the UI
 * renders envelopes, it never re-derives engine behaviour), so it is published by the engine as
 * `scenario_resolution_order` in the committed `docs/vocabulary.json` — the parse-time recovery stage
 * (`missing_species`, `truncate_corrupt_tail`, `ambiguous_units`, `ambiguous_atom_style`, resolved
 * *before* parsing completes — the last is the LAMMPS-data style pick, M48-S1, D180)
 * followed by the conversion-time dependency order (frame_selection → constraint → lattice → masses →
 * velocities → ambiguous_stress_convention → ambiguous_units, the write-side trigger landing last in
 * M47-S1, D177).
 *
 * This constant mirrors that artifact; `order.test.ts` asserts they are equal, so it can never drift
 * the way the old hand-copied `DEP_ORDER` did — and, unlike that copy, it sorts the parse-time
 * scenarios ahead of the conversion-time ones instead of dumping them at the tail.
 */

import type { AwaitingScenario } from "@/lib/report/types";

/** The engine's recovery resolution order — kept in lockstep with `docs/vocabulary.json` by a test. */
export const RECOVERY_RESOLUTION_ORDER: readonly string[] = [
  "missing_species",
  "truncate_corrupt_tail",
  "ambiguous_units",
  "ambiguous_atom_style",
  "frame_selection",
  "constraint_representation",
  "missing_lattice",
  "missing_masses",
  "missing_velocities",
  "ambiguous_stress_convention",
  "ambiguous_units",
];

/**
 * Sort a pause's scenarios into engine resolution order. A scenario the engine does not list (a
 * future plugin's) is unknown here; it sorts after every known one, keeping its position within the
 * block so the render stays stable and functional (P6) rather than guessing an order.
 */
export function orderedScenarios(scenarios: AwaitingScenario[]): AwaitingScenario[] {
  const rank = (scenario: AwaitingScenario, index: number) => {
    const known = RECOVERY_RESOLUTION_ORDER.indexOf(scenario.scenario);
    return known === -1 ? RECOVERY_RESOLUTION_ORDER.length + index : known;
  };
  return scenarios
    .map((scenario, index) => ({ scenario, key: rank(scenario, index) }))
    .sort((a, b) => a.key - b.key)
    .map((entry) => entry.scenario);
}
