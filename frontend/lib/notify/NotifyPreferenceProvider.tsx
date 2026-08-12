"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { requestNotificationPermission } from "./completionSignal";

/**
 * The completion-signal preference (v1.1 M39-S4, C1) — the persisted on/off switch for the Web UI
 * completion signal (chime + Notification), mirroring the theme system's shape
 * (`lib/theme/ThemeProvider.tsx`).
 *
 * **Default is on** (deliberately unlike the theme, whose default is light): the signal is purely
 * additive UX, and the maintainer's decision is on-by-default with an opt-out. The user's choice is
 * remembered in `localStorage`; there is no no-FOUC script needed because the default (on) is also
 * the first-paint state — a persisted "off" only mutes, it never flashes anything.
 *
 * Notification permission is requested when the user **enables** the toggle (the click is the
 * user gesture the browser requires) — never on page load.
 */

/** localStorage key for the on/off flag ("1" = on, "0" = off). */
export const NOTIFY_STORAGE_KEY = "xtalate-notify";

interface NotifyPreferenceContextValue {
  /** Whether the completion signal plays (chime + notification). Default on. */
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
  toggle: () => void;
}

const NotifyPreferenceContext = createContext<NotifyPreferenceContextValue | null>(null);

function readStored(): boolean | null {
  try {
    const value = localStorage.getItem(NOTIFY_STORAGE_KEY);
    if (value === "1") return true;
    if (value === "0") return false;
    return null; // never stored → the default (on)
  } catch {
    return null; // localStorage can throw (privacy mode); fall back to the default.
  }
}

function persist(enabled: boolean): void {
  try {
    localStorage.setItem(NOTIFY_STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // Persistence is best-effort; the session still honors the choice.
  }
}

export function NotifyPreferenceProvider({ children }: { children: ReactNode }) {
  // SSR and the very first client render agree on "on" so hydration never mismatches; the mount
  // effect then adopts whatever localStorage remembers.
  const [enabled, setEnabledState] = useState(true);

  useEffect(() => {
    const stored = readStored();
    if (stored !== null) setEnabledState(stored);
  }, []);

  const setEnabled = useCallback((next: boolean) => {
    setEnabledState(next);
    persist(next);
    // Enabling is an explicit user act — the natural moment to ask for notification permission
    // (the browser requires a gesture; the toggle click provides it). Never on page load.
    if (next) void requestNotificationPermission();
  }, []);

  const toggle = useCallback(() => {
    setEnabledState((prev) => {
      const next = !prev;
      persist(next);
      if (next) void requestNotificationPermission();
      return next;
    });
  }, []);

  return (
    <NotifyPreferenceContext.Provider value={{ enabled, setEnabled, toggle }}>
      {children}
    </NotifyPreferenceContext.Provider>
  );
}

export function useNotifyPreference(): NotifyPreferenceContextValue {
  const ctx = useContext(NotifyPreferenceContext);
  if (!ctx) throw new Error("useNotifyPreference must be used within a NotifyPreferenceProvider");
  return ctx;
}

/**
 * The mute toggle (C1), mounted in the app-shell header beside the theme toggle: a bell while the
 * signal is on, a bell-off while muted, `aria-pressed` reporting the enabled state and the
 * accessible name stating the action. A self-contained client island, exactly like the theme
 * toggle, so the whole mechanism is unit-testable.
 */
export function NotifyToggle({ className }: { className?: string }) {
  const { enabled, toggle } = useNotifyPreference();
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={enabled}
      aria-label={enabled ? "Mute completion signal" : "Unmute completion signal"}
      title={enabled ? "Mute completion signal" : "Unmute completion signal"}
      className={
        className ??
        "inline-flex h-9 w-9 items-center justify-center rounded-md border border-line text-muted transition-colors hover:bg-raised hover:text-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      }
    >
      {enabled ? <BellIcon /> : <BellOffIcon />}
    </button>
  );
}

function BellIcon() {
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
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

function BellOffIcon() {
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
      <path d="M8.7 3A6 6 0 0 1 18 8c0 3.4.9 5.4 2 7.1M6.1 6.1A5.9 5.9 0 0 0 6 8c0 7-3 9-3 9h11" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      <path d="M3 3l18 18" />
    </svg>
  );
}
