import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, THEME_STORAGE_KEY } from "@/lib/theme/ThemeProvider";
import { ThemeControl } from "./ThemeControl";

beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation((q: string) => ({
    matches: false,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("ThemeControl", () => {
  it("is a labelled group of three toggle buttons with System pressed by default", () => {
    render(<ThemeProvider><ThemeControl /></ThemeProvider>);
    const group = screen.getByRole("group", { name: "Theme" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Use system theme",
      "Use light theme",
      "Use dark theme",
    ]);
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual(["true", "false", "false"]);
  });

  it("choosing Dark presses it, sets data-theme and persists", async () => {
    render(<ThemeProvider><ThemeControl /></ThemeProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Use dark theme" }));
    expect(screen.getByRole("button", { name: "Use dark theme" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Use system theme" }).getAttribute("aria-pressed")).toBe("false");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});
