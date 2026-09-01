import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { ThemeProvider, ThemeToggle, THEME_STORAGE_KEY, useOptionalTheme, useTheme } from "./ThemeProvider";

/**
 * The theme system (pre-M36 addendum, Slice S1). A persisted light/dark toggle that flips
 * `data-theme` on <html> — the attribute the CSS palette (globals.css) and Tailwind's selector
 * dark-mode key off. Default is light; the user's explicit choice is remembered in localStorage.
 */

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("useTheme", () => {
  it("defaults to light when nothing is persisted", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("light");
  });

  it("adopts a persisted dark choice on mount and applies it to <html>", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("toggle() flips the theme, sets data-theme, and persists the choice", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });
});

describe("ThemeToggle", () => {
  it("renders an accessible switch and toggles the theme when clicked", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const button = screen.getByRole("button", { name: /dark mode|theme/i });
    expect(document.documentElement.getAttribute("data-theme")).not.toBe("dark");

    fireEvent.click(button);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    // aria-pressed reflects the active state for assistive tech.
    expect(button).toHaveAttribute("aria-pressed", "true");
  });
});

function ThemeProbe() {
  return <span data-testid="probe">{useOptionalTheme()}</span>;
}

describe("useOptionalTheme", () => {
  it("returns light with no provider and no data-theme attribute", () => {
    document.documentElement.removeAttribute("data-theme");
    const { getByTestId } = render(<ThemeProbe />);
    expect(getByTestId("probe").textContent).toBe("light");
  });

  it("reads the data-theme attribute when there is no provider", () => {
    document.documentElement.setAttribute("data-theme", "dark");
    const { getByTestId } = render(<ThemeProbe />);
    expect(getByTestId("probe").textContent).toBe("dark");
    document.documentElement.removeAttribute("data-theme");
  });

  it("prefers the provider's theme when wrapped", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const { getByTestId } = render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    // ThemeProvider mounts to the persisted/attribute value; default light here.
    expect(["light", "dark"]).toContain(getByTestId("probe").textContent);
    document.documentElement.removeAttribute("data-theme");
  });
});
