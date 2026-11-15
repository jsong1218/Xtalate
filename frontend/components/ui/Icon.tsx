import type { LucideIcon } from "lucide-react";

/**
 * The one seam every icon passes through (redesign §9). Lucide icons are imported per-icon by the
 * caller (tree-shaken) and rendered here at 14 or 16 px with a 1.5 stroke. Decorative by default
 * (`aria-hidden`); pass `label` when the icon *is* the meaning (a status glyph with no visible text)
 * and it becomes `role="img"` with that name. Loss semantics still come from the `--cb-*` colour
 * classes the caller passes in `className`, never from the icon alone.
 */
export type IconSize = 14 | 16;

export interface IconProps {
  icon: LucideIcon;
  size?: IconSize;
  /** Accessible name; omit for a purely decorative icon beside visible text. */
  label?: string;
  className?: string;
}

export function Icon({ icon: Lucide, size = 16, label, className }: IconProps) {
  const a11y = label
    ? { role: "img" as const, "aria-label": label, "aria-hidden": undefined }
    : { "aria-hidden": true as const };
  return (
    <Lucide
      size={size}
      strokeWidth={1.5}
      focusable="false"
      className={className ? `shrink-0 ${className}` : "shrink-0"}
      {...a11y}
    />
  );
}
