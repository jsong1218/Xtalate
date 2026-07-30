import type { LossKind } from "@/components/loss/icons";
import type { Schemas } from "@/lib/api/client";

/** One `items[]` entry from `GET /v1/history`, verbatim from the generated schema (Part 6 §4.4). */
export type HistoryItem = Schemas["HistoryItem"];

export interface HistoryStatus {
  kind: LossKind;
  label: string;
}

/**
 * Map a history row's two status fields onto the §4 loss vocabulary (Part 7 §2.6; slice M33-S2).
 *
 * This is a **presentation mapping over the existing vocabulary**, not a second visual language for
 * the table — the same rule the format explorer's capability glyph follows. §4 assigns the `fail`
 * glyph to *both* a validation failure and a refusal, so both resolve to `fail` here and are told
 * apart only by their label (color is never the sole carrier). A completed conversion whose
 * validation merely warned is a `warning`, not a clean pass; an unrecognised or absent conversion
 * status is rendered honestly (`skipped`, "Unknown") rather than optimistically assumed to be a
 * success — the row renders exactly what the envelope carries.
 */
export function historyStatus(
  item: Pick<HistoryItem, "conversion_status" | "validation_status">,
): HistoryStatus {
  if (item.conversion_status === "refused") return { kind: "fail", label: "Refused" };
  if (item.conversion_status === "completed") {
    if (item.validation_status === "failed") return { kind: "fail", label: "Validation failed" };
    if (item.validation_status === "passed_with_warnings") {
      return { kind: "warning", label: "Validation warnings" };
    }
    // "passed" or no validation recorded — the conversion wrote its output.
    return { kind: "preserved", label: "Converted" };
  }
  return { kind: "skipped", label: "Unknown" };
}
