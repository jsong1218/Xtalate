import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  NOTIFY_STORAGE_KEY,
  NotifyPreferenceProvider,
  NotifyToggle,
  useNotifyPreference,
} from "./NotifyPreferenceProvider";

/**
 * The completion-signal preference (v1.1 M39-S4, C1) — a persisted on/off flag mirroring the theme
 * system: **default on** (the signal is additive UX), remembered in localStorage, and permission
 * requested only when the user enables the signal — never on page load.
 */

class FakeNotification {
  static permission: NotificationPermission = "default";
  static requestPermission = vi.fn(async (): Promise<NotificationPermission> => "granted");
}

function wrapper({ children }: { children: ReactNode }) {
  return <NotifyPreferenceProvider>{children}</NotifyPreferenceProvider>;
}

beforeEach(() => {
  localStorage.clear();
  FakeNotification.requestPermission = vi.fn(
    async (): Promise<NotificationPermission> => "granted",
  );
  vi.stubGlobal("Notification", FakeNotification);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useNotifyPreference", () => {
  it("defaults to ON when nothing is persisted", () => {
    const { result } = renderHook(() => useNotifyPreference(), { wrapper });
    expect(result.current.enabled).toBe(true);
    // Enabling default-on must not trigger a permission request on page load.
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
  });

  it("adopts a persisted off choice on mount", () => {
    localStorage.setItem(NOTIFY_STORAGE_KEY, "0");
    const { result } = renderHook(() => useNotifyPreference(), { wrapper });
    expect(result.current.enabled).toBe(false);
  });

  it("toggle() flips the flag and persists it", () => {
    const { result } = renderHook(() => useNotifyPreference(), { wrapper });
    expect(localStorage.getItem(NOTIFY_STORAGE_KEY)).toBeNull(); // default-on is not written

    act(() => result.current.toggle());
    expect(result.current.enabled).toBe(false);
    expect(localStorage.getItem(NOTIFY_STORAGE_KEY)).toBe("0");

    act(() => result.current.toggle());
    expect(result.current.enabled).toBe(true);
    expect(localStorage.getItem(NOTIFY_STORAGE_KEY)).toBe("1");
  });

  it("re-enabling the signal requests notification permission (the user gesture)", () => {
    localStorage.setItem(NOTIFY_STORAGE_KEY, "0"); // start muted
    const { result } = renderHook(() => useNotifyPreference(), { wrapper });
    expect(result.current.enabled).toBe(false);
    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();

    act(() => result.current.toggle());
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1);
  });
});

describe("NotifyToggle", () => {
  it("renders a labelled bell, on by default, and mutes when clicked", () => {
    render(
      <NotifyPreferenceProvider>
        <NotifyToggle />
      </NotifyPreferenceProvider>,
    );
    const button = screen.getByRole("button", { name: "Mute completion signal" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem(NOTIFY_STORAGE_KEY)).toBeNull();

    fireEvent.click(button);
    expect(screen.getByRole("button", { name: "Unmute completion signal" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(localStorage.getItem(NOTIFY_STORAGE_KEY)).toBe("0");
  });
});
