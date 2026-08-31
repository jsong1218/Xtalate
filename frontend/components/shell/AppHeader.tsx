import Link from "next/link";
import { CommandPaletteTrigger } from "@/components/command/CommandPaletteTrigger";
import { NotifyToggle } from "@/lib/notify/NotifyPreferenceProvider";
import { ThemeToggle } from "@/lib/theme/ThemeProvider";

/**
 * The app-shell header (pre-M36 frontend-redesign addendum, Slice S2; design spec §4.2).
 *
 * Rendered once from `app/layout.tsx`, so the same navigation, the light/dark toggle, and the
 * completion-signal mute toggle sit in the same place on every page — the shell that replaces the
 * old ad-hoc, per-page inline links. Left: the Xtalate wordmark, the universal way home. Middle:
 * the primary destinations. Right: the theme toggle and the notify mute toggle (which read the
 * providers the layout wraps this in; v1.1 M39-S4 C1 added the bell).
 *
 * A server component — nothing here needs client state (the two toggles are the client islands).
 * The nav is `aria-label="Primary"` so it is a distinct landmark from the `/docs` section nav
 * ("Documentation").
 *
 * Layout: the wordmark and the toggles never shrink; the nav takes the middle and wraps its own
 * links onto a second line on a narrow screen (`min-w-0 flex-1`), so the bar grows taller rather
 * than forcing the page to scroll sideways.
 */

const PRIMARY_NAV: { href: string; label: string }[] = [
  // Upload lives on the landing since the UI redesign (S2): `/convert` redirects to `/`, so the
  // header points at the real surface (the hero CTA opens the same dropzone).
  { href: "/", label: "Convert" },
  { href: "/formats", label: "Formats" },
  { href: "/history", label: "History" },
  { href: "/docs", label: "Docs" },
];

export function AppHeader() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-5xl items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link
          href="/"
          className="shrink-0 rounded-sm text-lg font-semibold tracking-tight text-strong transition-colors hover:text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
        >
          Xtalate
        </Link>
        <nav
          aria-label="Primary"
          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1 text-sm"
        >
          {PRIMARY_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-sm text-muted transition-colors hover:text-accent-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="flex shrink-0 items-center gap-2">
          {/* The ⌘K command palette (UI redesign S4): visible button + global ⌘K/Ctrl-K shortcut. */}
          <CommandPaletteTrigger />
          <NotifyToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
