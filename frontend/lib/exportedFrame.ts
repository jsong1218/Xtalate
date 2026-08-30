import type { ConversionReport } from "@/lib/report/types";

/**
 * The report-sourced exported-frame annotation (v1.6 M61-S2, D237; lifted here from
 * `StructureTab.tsx` for M62-S1 — a *move, not a rewrite*, so the Compare tab and the Structure tab
 * share one lookup, never a fork).
 *
 * When a conversion's output was produced by a `frame_selection` recovery, this names which
 * **source frame** the output is — read **only** from the Assumption's `parameters.frame_index`
 * (the engine resolves the absolute, 0-based source index for `first`/`last`/`index` alike —
 * `src/xtalate/recovery/engine.py` `_frame_selection_assumption`), never client re-derived:
 * no `last → frame_count - 1` arithmetic, no source/output position diffing (the no-scientific-
 * logic-in-the-client boundary, v0.6 / D235).
 *
 * `split_all` is HTTP-refused (D113) so it should never reach a conversion record, and an absent /
 * non-integer `frame_index` renders **no annotation** — never `NaN` (belt-and-braces guards, not
 * the main path). Returns `undefined` on a discovery page (no `assumptions`) or a conversion with
 * no `frame_selection` Assumption.
 */
export function exportedFrameAnnotation(
  conversionReport?: ConversionReport,
): { index: number; assumptionId: string } | undefined {
  const assumption = conversionReport?.assumptions.find(
    (a) => a.scenario === "frame_selection",
  );
  if (!assumption) return undefined;
  const raw = assumption.parameters?.frame_index;
  if (typeof raw !== "number" || !Number.isInteger(raw)) return undefined;
  return { index: raw, assumptionId: assumption.id };
}