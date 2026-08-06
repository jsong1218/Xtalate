import { forwardRef, type ButtonHTMLAttributes } from "react";

/**
 * The shared primary-action primitive (pre-M36 frontend-redesign addendum S3).
 *
 * The design language (spec §4.3) gives forward-moving actions — Upload, Continue, Convert,
 * Download, Finish — one unmistakable treatment (a filled accent), and lets everything else recede:
 * `secondary` (bordered, subtle), `ghost` (quiet, text-only), and `destructive` (the filled-fail
 * treatment reserved for delete-style actions). Defining that vocabulary **once** here is what keeps
 * it consistent across the wizard: a call site picks a variant and a size, never a bespoke string of
 * colour utilities, so a token or focus-ring change lands everywhere at once.
 *
 * The accent is a forward-action colour only. It is **never** used for loss semantics — the `--cb-*`
 * palette (Part 7 §4) keeps that job — so a blue "Convert" button can never be mistaken for a
 * green/amber/red loss signal. Both accent stops clear WCAG AA against their fill in both themes,
 * guarded by `globals.contrast.test.ts`.
 *
 * {@link buttonClasses} is exported so a Next `<Link>` (a navigation that is really a forward action,
 * e.g. the landing "Convert a file" call to action or the "View the full record" finish step) can
 * wear the exact same look without this component having to re-implement anchor semantics.
 */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
export type ButtonSize = "sm" | "md" | "lg";

// Shared chrome: inline-flex so an icon + label align; a functional focus-visible ring (no decorative
// animation, ~150ms); and a single disabled affordance every variant inherits.
const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-surface " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover",
  secondary: "border border-line bg-surface text-body hover:bg-raised",
  ghost: "text-muted hover:bg-raised hover:text-strong",
  destructive: "bg-cb-fail-solid text-white hover:opacity-90",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-base",
};

/** The class string for a given look — usable on `<button>`, `<a>`, or a Next `<Link>`. */
export function buttonClasses(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
  return `${BASE} ${VARIANTS[variant]} ${SIZES[size]}`;
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

/**
 * A `<button>` wearing {@link buttonClasses}. Defaults to `type="button"` (never a stray form
 * submit) and to the `primary` variant. Any extra `className` is appended for layout-only utilities
 * (`w-full`, margins); it must not be used to override a variant's colour — pick the right variant.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", type = "button", className, children, ...rest },
  ref,
) {
  const classes = className
    ? `${buttonClasses(variant, size)} ${className}`
    : buttonClasses(variant, size);
  return (
    <button ref={ref} type={type} className={classes} {...rest}>
      {children}
    </button>
  );
});
