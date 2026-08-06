import { LossIcon, type LossKind } from "@/components/loss/icons";
import type { CapabilityLevel } from "@/lib/capabilities/types";

/**
 * How a capability *level* borrows the §4 loss vocabulary (slice M33-S1). The matrix needs a
 * three-way visual — full / partial / none — but §4 defines no "partial" glyph, and inventing one
 * would be a second visual language the standing rules forbid. So each level reuses an existing kind
 * whose meaning already matches:
 *
 *  - **full** → `preserved` (✓): the format expresses this field completely.
 *  - **partial** → `assumption` (◆): the icon set defines ◆ as "a third thing: not preserved, not
 *    loss" — exactly a *conditional* capability, expressible only under the caveat the notes state.
 *  - **none** → `absent-format` (✗, calm): literally "the format cannot hold this", the §4 meaning
 *    of ✗-muted and the same safe default an undeclared field takes (Part 3 §4.3).
 *
 * This is a presentation mapping over the existing vocabulary, not a new one — the grid and the
 * detail view both render through here so they can never disagree.
 */
export const CAPABILITY_KIND: Record<CapabilityLevel, LossKind> = {
  full: "preserved",
  partial: "assumption",
  none: "absent-format",
};

/** The word shown beside the glyph — color is never the sole carrier (§4). */
export const CAPABILITY_LABEL: Record<CapabilityLevel, string> = {
  full: "Full",
  partial: "Partial",
  none: "None",
};

/**
 * A capability level as an accessible glyph, prefixed by the direction it describes. The icon's
 * `aria-label` is the full phrase ("Write Full", "Read Partial"), so assistive tech and a
 * color-blind reader get the level and the direction without the hue, exactly like {@link LossIcon}.
 */
export function CapabilityGlyph({
  direction,
  level,
}: {
  direction: "read" | "write";
  level: CapabilityLevel;
}) {
  const dirLabel = direction === "read" ? "Read" : "Write";
  return (
    <span className="inline-flex items-center gap-1">
      <span aria-hidden="true" className="font-mono text-[0.7rem] uppercase text-faint">
        {direction === "read" ? "R" : "W"}
      </span>
      <LossIcon kind={CAPABILITY_KIND[level]} label={`${dirLabel} ${CAPABILITY_LABEL[level]}`} />
    </span>
  );
}
