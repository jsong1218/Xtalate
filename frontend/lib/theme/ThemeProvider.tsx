"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

/**
 * The theme system (pre-M36 frontend-redesign addendum, Slice S1).
 *
 * A light/dark toggle that flips the `data-theme` attribute on <html> — the single switch the CSS
 * palette (`app/globals.css`) and Tailwind's selector dark-mode (`tailwind.config.ts`) both key off.
 * **Default is light**; the user's explicit choice is remembered in `localStorage`, so it does NOT
 * follow `prefers-color-scheme` (this is the deliberate choice recorded in globals.css, overriding
 * D96). The no-flash `<head>` script in `app/layout.tsx` applies the persisted choice before first
 * paint; this provider then adopts it on mount and owns every change afterward.
 *
 * There is deliberately no cross-page store beyond this (Part 7 §5.1) — the theme is the one piece of
 * genuinely client-only, cross-page UI state, and it lives in a DOM attribute + localStorage, not a
 * data store.
 */

export type Theme = "light" | "dark";

/** localStorage key — shared with the no-FOUC script in layout.tsx (keep them in sync). */
export const THEME_STORAGE_KEY = "xtalate-theme";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // localStorage can throw (privacy mode); fall back to the default.
  }
}

function persist(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Persistence is best-effort; the attribute below still applies for this session.
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // SSR and the very first client render agree on "light" so hydration never mismatches; the mount
  // effect then adopts whatever the no-FOUC script already applied / localStorage remembers.
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    const stored = readStored();
    if (stored) setThemeState(stored);
  }, []);

  // The attribute is the source of truth the stylesheet reads; keep it in lockstep with state.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    persist(next);
  }, []);

  const toggle = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === "light" ? "dark" : "light";
      persist(next);
      return next;
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggle }}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}

/**
 * A non-throwing theme read for leaf widgets that may render outside a ThemeProvider (e.g. the
 * Mol* mount under a bare `render()` in unit tests). Returns the context theme when a provider is
 * present — so it re-renders on toggle in the real app, where Providers always wrap the tree —
 * otherwise falls back to the `data-theme` attribute the no-FOUC script sets, defaulting to light.
 */
export function useOptionalTheme(): Theme {
  const ctx = useContext(ThemeContext);
  if (ctx) return ctx.theme;
  if (typeof document !== "undefined") {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "dark" || attr === "light") return attr;
  }
  return "light";
}

/**
 * The theme toggle control. Mounted into the app-shell header in Slice S2; a self-contained button
 * here so the whole mechanism is testable now. Shows a sun in dark mode (tap to lighten) and a moon
 * in light mode (tap to darken); the accessible name states the action and `aria-pressed` reports
 * whether dark mode is active.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={dark}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      className={
        className ??
        "inline-flex h-9 w-9 items-center justify-center rounded-md border border-line text-muted transition-colors hover:bg-raised hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      }
    >
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}
