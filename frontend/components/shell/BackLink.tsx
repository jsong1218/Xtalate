import Link from "next/link";

/**
 * The consistent back affordance (pre-M36 frontend-redesign addendum, Slice S2; design spec §4.2).
 *
 * A left-arrow control placed in the upper-left of every non-landing page, in the same place
 * everywhere. It takes an **explicit parent route** rather than calling `router.back()` so the
 * destination is predictable no matter how the page was reached (a deep link, a refreshed tab, an
 * arrival from search) — the "never trapped" rule. The arrow is decorative; the accessible name
 * ("Back to {label}") states the action and contains the visible label, satisfying WCAG 2.5.3.
 */
export function BackLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      aria-label={`Back to ${label}`}
      className="inline-flex items-center gap-1.5 rounded-sm text-sm text-muted transition-colors hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M19 12H5" />
        <path d="M12 19l-7-7 7-7" />
      </svg>
      <span>{label}</span>
    </Link>
  );
}
