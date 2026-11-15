import type { LucideIcon } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Icon, type IconSize } from "./Icon";

/**
 * A square icon-only button with a mandatory accessible name (redesign §9: every text-glyph control
 * becomes an icon button with `aria-label`). `pressed` turns it into a toggle button (`aria-pressed`),
 * which is how the three-state theme control and the mute toggle expose state. Same focus ring as
 * `Button`; the pressed look is driven by `aria-pressed` so state and style cannot disagree.
 */
export interface IconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "aria-label"> {
  icon: LucideIcon;
  /** The accessible name (also the tooltip). */
  label: string;
  /** When defined, renders a toggle button with `aria-pressed`. */
  pressed?: boolean;
  size?: IconSize;
}

const BASE =
  "inline-flex items-center justify-center rounded text-muted transition-colors " +
  "hover:bg-raised hover:text-strong " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-surface " +
  "aria-pressed:bg-well aria-pressed:text-strong " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const SIZES: Record<IconSize, string> = { 14: "h-6 w-6", 16: "h-8 w-8" };

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, pressed, size = 16, className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={className ? `${BASE} ${SIZES[size]} ${className}` : `${BASE} ${SIZES[size]}`}
      {...rest}
    >
      <Icon icon={icon} size={size} />
    </button>
  );
});
