import { LossIcon } from "@/components/loss/icons";

/**
 * The Assumption preview (MASTER_SPEC Part 7 §3, P4; slice M31-S1).
 *
 * Consent and provenance are the same artifact: before a user confirms a recovery choice, they see
 * the **exact** sentence that will be recorded as an Assumption in the Conversion Report. The text
 * is not composed here — it comes verbatim from the engine's own preview (`POST …/recovery/preview`),
 * so what the card shows and what the record stores are one string, never a paraphrase (P2). Shown
 * in the shared ◆ assumption tone the report panels use, so a reader recognises it as the same thing.
 */
export function AssumptionPreview({ description }: { description: string }) {
  return (
    <div
      data-testid="assumption-preview"
      className="space-y-1 rounded-md border border-cb-assumption bg-cb-assumption-bg p-3"
    >
      <div className="flex items-center gap-2">
        <LossIcon kind="assumption" />
        <span className="text-xs font-semibold uppercase tracking-wide text-cb-assumption">
          This will be recorded as an assumption
        </span>
      </div>
      <p className="text-sm text-slate-800">{description}</p>
    </div>
  );
}
