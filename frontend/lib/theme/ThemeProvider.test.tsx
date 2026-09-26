import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { ThemeProvider, ThemeToggle, THEME_STORAGE_KEY, useOptionalTheme, useTheme } from "./ThemeProvider";

/**
 * The theme system (pre-M36 addendum, Slice S1; default flipped to dark by v2.0 addendums Task 6,
 * the Steel workbench palette). A persisted light/dark toggle that flips `data-theme` on <html> —
 * the attribute the CSS palette (globals.css) and Tailwind's selector dark-mode key off. Default is
 * dark; the user's explicit choice is remembered in localStorage.
 */

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("useTheme", () => {
  it("defaults to dark when nothing is persisted", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("dark");
  });

  it("adopts a persisted light choice on mount and applies it to <html>", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("toggle() flips the theme, sets data-theme, and persists the choice", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});

describe("ThemeToggle", () => {
  it("renders an accessible switch and toggles the theme when clicked", () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    const button = screen.getByRole("button", { name: /light mode|dark mode|theme/i });
    // Default is dark, so the initial affordance offers to switch to light.
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(button).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(button);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(button).toHaveAttribute("aria-pressed", "false");
  });
});

function ThemeProbe() {
  return <span data-testid="probe">{useOptionalTheme()}</span>;
}

describe("useOptionalTheme", () => {
  it("returns dark with no provider and no data-theme attribute", () => {
    document.documentElement.removeAttribute("data-theme");
    const { getByTestId } = render(<ThemeProbe />);
    expect(getByTestId("probe").textContent).toBe("dark");
  });

  it("reads the data-theme attribute when there is no provider", () => {
    document.documentElement.setAttribute("data-theme", "light");
    const { getByTestId } = render(<ThemeProbe />);
    expect(getByTestId("probe").textContent).toBe("light");
    document.documentElement.removeAttribute("data-theme");
  });

  it("prefers the provider's theme when wrapped", () => {
    // Set the attribute to "light", but the provider will initialize to "dark" (default, no
    // localStorage). If the hook reads the attribute, it returns "light"; if it reads context, it
    // returns "dark". This discriminates the two implementations.
    document.documentElement.setAttribute("data-theme", "light");
    const { getByTestId } = render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(getByTestId("probe").textContent).toBe("dark");
    document.documentElement.removeAttribute("data-theme");
  });
});
