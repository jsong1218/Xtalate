import Link from "next/link";

/**
 * The wordmark (redesign §4, §9): "Xtalate" in Plex Serif 600 beside a single lattice-dot mark — one
 * site of a lattice drawn as two hairline bonds meeting at an accent-coloured atom. The mark is
 * decorative; the link's name is the word. Also the only place outside stage 5 that uses the serif.
 */
export function Wordmark() {
  return (
    <Link
      href="/"
      className="inline-flex shrink-0 items-center gap-2 rounded-sm font-serif text-md font-semibold tracking-tight text-strong transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-wb-toolbar"
    >
      <svg
        aria-hidden="true"
        focusable="false"
        width="16"
        height="16"
        viewBox="0 0 16 16"
        className="shrink-0"
      >
        <line x1="2" y1="14" x2="8" y2="8" stroke="currentColor" strokeWidth="1" opacity="0.6" />
        <line x1="8" y1="8" x2="14" y2="8" stroke="currentColor" strokeWidth="1" opacity="0.6" />
        <circle cx="8" cy="8" r="2.5" fill="var(--accent)" />
      </svg>
      <span>Xtalate</span>
    </Link>
  );
}
