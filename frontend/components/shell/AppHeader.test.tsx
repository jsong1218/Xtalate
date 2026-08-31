import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppHeader } from "./AppHeader";
import { NotifyPreferenceProvider } from "@/lib/notify/NotifyPreferenceProvider";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";

/**
 * The app-shell header (pre-M36 frontend-redesign addendum, Slice S2): a home wordmark on the left,
 * the primary nav, and the theme + completion-signal mute toggles on the right (the notify toggle
 * joined in v1.1 M39-S4 C1) — present on every page so navigation and the switches are always in
 * the same place. The toggles need their providers' contexts, so the header is rendered within them
 * here (as it is in the real tree).
 */
function renderHeader() {
  return render(
    <ThemeProvider>
      <NotifyPreferenceProvider>
        <AppHeader />
      </NotifyPreferenceProvider>
    </ThemeProvider>,
  );
}

describe("AppHeader", () => {
  it("renders a banner landmark", () => {
    renderHeader();
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("puts the Xtalate wordmark first, linking home", () => {
    renderHeader();
    expect(screen.getByRole("link", { name: "Xtalate" })).toHaveAttribute("href", "/");
  });

  it("offers the primary destinations in a named nav", () => {
    renderHeader();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const expected: [string, string][] = [
      // Upload lives on the landing (UI redesign S2); `/convert` redirects to `/`.
      ["Convert", "/"],
      ["Formats", "/formats"],
      ["History", "/history"],
      ["Docs", "/docs"],
    ];
    for (const [label, href] of expected) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("uses the accent-text token for interactive nav emphasis, not a hard-coded colour", () => {
    renderHeader();
    const convert = screen.getByRole("link", { name: "Convert" });
    // Hover/active emphasis is the themed accent-text token, so it flips correctly in dark mode.
    expect(convert.className).toContain("accent-text");
    // No hard-coded slate/blue for the themed role.
    expect(convert.className).not.toMatch(/text-blue-|text-slate-/);
  });

  it("mounts the theme toggle", () => {
    renderHeader();
    // Default is light, so the toggle offers to switch to dark.
    expect(screen.getByRole("button", { name: /switch to dark mode/i })).toBeInTheDocument();
  });

  it("mounts the completion-signal mute toggle, on by default (C1)", () => {
    renderHeader();
    // Default is on (the signal is additive), so the bell offers to mute.
    expect(screen.getByRole("button", { name: "Mute completion signal" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
