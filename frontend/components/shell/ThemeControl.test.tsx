import { act, render, screen, within } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
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

  it("presses the stored preference's button after hydration, not the server's System", async () => {
    // The server has no window, so it renders preference "system"; a client with a stored choice
    // hydrates differently. React does not patch attribute mismatches, so nothing may be pressed
    // until after mount.
    const tree = (
      <ThemeProvider>
        <ThemeControl />
      </ThemeProvider>
    );
    const container = document.createElement("div");
    document.body.appendChild(container);
    container.innerHTML = renderToString(tree);
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    await act(async () => {
      hydrateRoot(container, tree);
    });
    expect(screen.getByRole("button", { name: "Use dark theme" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Use system theme" }).getAttribute("aria-pressed")).toBe("false");
    container.remove();
  });
});
