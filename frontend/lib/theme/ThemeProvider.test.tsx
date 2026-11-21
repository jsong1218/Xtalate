import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  readStoredPreference,
  resolveTheme,
  ThemeProvider,
  THEME_STORAGE_KEY,
  useOptionalTheme,
  useTheme,
} from "./ThemeProvider";

/**
 * The theme system after the redesign (D-B7, reversing the D300 dark-first default): the preference
 * is `system | light | dark`, persisted under the existing key; the resolved theme follows the OS
 * while the preference is `system` and is pinned otherwise. `data-theme` on <html> is what the CSS
 * palette and Tailwind's selector dark mode key off, so every path must land there.
 */

type Listener = (e: { matches: boolean }) => void;
let systemDark = false;
const listeners = new Set<Listener>();

function installMatchMedia() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("dark") ? systemDark : !systemDark,
    media: query,
    addEventListener: (_: "change", cb: Listener) => listeners.add(cb),
    removeEventListener: (_: "change", cb: Listener) => listeners.delete(cb),
  })) as unknown as typeof window.matchMedia;
}
function flipSystem(dark: boolean) {
  systemDark = dark;
  listeners.forEach((cb) => cb({ matches: dark }));
}

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

beforeEach(() => {
  systemDark = false;
  listeners.clear();
  installMatchMedia();
});
afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("resolveTheme / readStoredPreference", () => {
  it("system follows the OS; explicit choices pin", () => {
    expect(resolveTheme("system", "dark")).toBe("dark");
    expect(resolveTheme("system", "light")).toBe("light");
    expect(resolveTheme("light", "dark")).toBe("light");
    expect(resolveTheme("dark", "light")).toBe("dark");
  });

  it("treats absent or invalid storage as system", () => {
    expect(readStoredPreference()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readStoredPreference()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    expect(readStoredPreference()).toBe("dark");
  });
});

describe("useTheme", () => {
  it("defaults to the system preference and resolves from the OS", () => {
    systemDark = true;
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.preference).toBe("system");
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("follows an OS change while the preference is system", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("light");
    act(() => flipSystem(true));
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("adopts a persisted explicit choice and ignores the OS afterwards", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    systemDark = true;
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.preference).toBe("light");
    expect(result.current.theme).toBe("light");
    act(() => flipSystem(false));
    act(() => flipSystem(true));
    expect(result.current.theme).toBe("light");
  });

  it("setPreference persists, resolves, and re-arms the OS listener for system", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    act(() => result.current.setPreference("dark"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    act(() => result.current.setPreference("system"));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
    expect(result.current.theme).toBe("light");
    act(() => flipSystem(true));
    expect(result.current.theme).toBe("dark");
  });

  it("throws outside the provider", () => {
    expect(() => renderHook(() => useTheme())).toThrow(/ThemeProvider/);
  });
});

describe("useOptionalTheme", () => {
  it("falls back to dark with no provider and no attribute", () => {
    const { result } = renderHook(() => useOptionalTheme());
    expect(result.current).toBe("dark");
  });
  it("reads data-theme when there is no provider", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const { result } = renderHook(() => useOptionalTheme());
    expect(result.current).toBe("light");
  });
  it("prefers the provider's resolved theme", () => {
    document.documentElement.setAttribute("data-theme", "light");
    systemDark = true;
    const { result } = renderHook(() => useOptionalTheme(), { wrapper });
    expect(result.current).toBe("dark");
  });
});
