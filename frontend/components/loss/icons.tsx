import type { ReactNode } from "react";

/**
 * The loss-communication icon set — MASTER_SPEC Part 7 §4, the one place the ✓/✗/○/◆/⚠/✕/–
 * vocabulary is defined. Every meaning is a fixed pairing of glyph + color token + text label, and
 * **color is never the sole carrier**: {@link LossTag} always renders a text label beside the
 * glyph, and the bare {@link LossIcon} carries an `aria-label` so assistive tech and
 * color-blind readers get the meaning without the hue. Later parts (M27 report panels, M28
 * inventory rows) compose these atoms; they must not reinvent the language (§4 "learned once,
 * trusted everywhere").
 */

export type LossKind =
  // Discovery `present`, Report `preserved`, Validation `pass`.
  | "preserved"
  // Discovery `absent` + `format_capability: none` — a fact about the *format*, visually calm.
  | "absent-format"
  // Discovery `absent` + capability `full`/`partial` — "your *file* could have this".
  | "absent-file"
  // Report `removed` — always shown with its `reason` inline.
  | "removed"
  // Report `assumptions` and `supplied`; recovery previews. A third thing: not preserved, not loss.
  | "assumption"
  // Report `warnings`, parse issues, Validation `warn`.
  | "warning"
  // Validation `fail`, refusals.
  | "fail"
  // Validation `skipped` + `skip_reason`.
  | "skipped";

interface LossGlyph {
  /** The §4 glyph. */
  glyph: string;
  /** Default human label (overridable per use, but never omitted). */
  label: string;
  /** Tailwind text-color class bound to the `--cb-*` token (tailwind.config.ts). */
  color: string;
  /** True for "✕ in a filled circle" — rendered as a filled badge, not a bare glyph. */
  filled?: boolean;
}

export const LOSS_GLYPHS: Record<LossKind, LossGlyph> = {
  preserved: { glyph: "✓", label: "Preserved", color: "text-cb-preserve" },
  "absent-format": {
    glyph: "✗",
    label: "Format cannot hold this",
    color: "text-cb-absent-format",
  },
  "absent-file": { glyph: "○", label: "Not in this file", color: "text-cb-absent-file" },
  removed: { glyph: "✗", label: "Removed", color: "text-cb-removed" },
  assumption: { glyph: "◆", label: "Assumption", color: "text-cb-assumption" },
  warning: { glyph: "⚠", label: "Warning", color: "text-cb-warning" },
  fail: { glyph: "✕", label: "Failed", color: "text-cb-fail", filled: true },
  skipped: { glyph: "–", label: "Skipped", color: "text-cb-skipped" },
};

/**
 * The bare icon. Decorative to sighted users (the glyph), meaningful to everyone via `aria-label`
 * — which defaults to the §4 label so the icon is never a silent color swatch.
 */
export function LossIcon({
  kind,
  label,
  className = "",
}: {
  kind: LossKind;
  label?: string;
  className?: string;
}) {
  const spec = LOSS_GLYPHS[kind];
  const accessibleLabel = label ?? spec.label;
  if (spec.filled) {
    return (
      <span
        role="img"
        aria-label={accessibleLabel}
        className={`inline-flex h-[1.1em] w-[1.1em] items-center justify-center rounded-full bg-cb-fail text-[0.72em] font-bold leading-none text-white ${className}`}
      >
        <span aria-hidden="true">{spec.glyph}</span>
      </span>
    );
  }
  return (
    <span
      role="img"
      aria-label={accessibleLabel}
      className={`inline-block font-semibold leading-none ${spec.color} ${className}`}
    >
      <span aria-hidden="true">{spec.glyph}</span>
    </span>
  );
}

/**
 * Icon + visible text label — the default way to show a loss state. The label is always present
 * (color is never the sole carrier, §4); `children` overrides the default label text while keeping
 * the glyph/color/accessible-label bound to the kind.
 */
export function LossTag({
  kind,
  children,
  className = "",
}: {
  kind: LossKind;
  children?: ReactNode;
  className?: string;
}) {
  const spec = LOSS_GLYPHS[kind];
  const text = children ?? spec.label;
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <LossIcon kind={kind} />
      <span className={`text-sm font-medium ${spec.color}`}>{text}</span>
    </span>
  );
}
