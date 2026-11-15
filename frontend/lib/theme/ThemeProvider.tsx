"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/**
 * The theme system (pre-M36 addendum S1; system-default three-state since the pipeline-bench
 * redesign, D-B7). The *preference* is what the user chose — `system`, `light` or `dark` — persisted
 * under {@link THEME_STORAGE_KEY}; the *theme* is the resolved `light | dark` that lands on
 * `<html data-theme>` (the attribute the CSS palette and Tailwind's selector dark mode key off).
 * `system` follows `prefers-color-scheme` live through a `change` listener. The same resolution
 * runs before paint in the no-flash script in `app/layout.tsx`; the two must agree.
 *
 * Consumers that only need the resolved theme (the Mol* viewer background) keep the `Theme` type
 * and `useOptionalTheme()` unchanged.
 */
export type Theme = "light" | "dark";
export type ThemePreference = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "xtalate-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

export function isThemePreference(v: unknown): v is ThemePreference {
  return v === "system" || v === "light" || v === "dark";
}

/** The persisted preference; anything absent, unknown, or unreadable (privacy mode) is `system`. */
export function readStoredPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(v) ? v : "system";
  } catch {
    return "system";
  }
}

/** The OS scheme; `dark` when `matchMedia` is unavailable (SSR, old jsdom). */
export function systemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "dark";
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference, system: Theme): Theme {
  return preference === "system" ? system : preference;
}

interface ThemeContextValue {
  theme: Theme;
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Lazy initialisers: on the client the first render already knows the stored preference and the
  // OS scheme, so there is no dark→light flicker after hydration. On the server both fall back
  // (system / dark); nothing rendered depends on them, so there is no hydration mismatch — the
  // no-flash script has already set `data-theme` on <html> before React runs.
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    typeof window === "undefined" ? "system" : readStoredPreference(),
  );
  const [system, setSystem] = useState<Theme>(() => systemTheme());

  // Follow the OS only while the preference is `system`.
  useEffect(() => {
    if (preference !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = (e: { matches: boolean }) => setSystem(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  const theme = resolveTheme(preference, system);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    if (next === "system") setSystem(systemTheme());
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage unavailable (privacy mode): the choice still applies for this page.
    }
  }, []);

  const value = useMemo(
    () => ({ theme, preference, setPreference }),
    [theme, preference, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a <ThemeProvider>");
  return ctx;
}

/**
 * The resolved theme without requiring a provider — reads the `data-theme` attribute the no-flash
 * script set, falling back to dark. Used by mounts that may render outside the provider (tests, the
 * Mol* viewer).
 */
export function useOptionalTheme(): Theme {
  const ctx = useContext(ThemeContext);
  if (ctx) return ctx.theme;
  if (typeof document !== "undefined") {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "light" || attr === "dark") return attr;
  }
  return "dark";
}
