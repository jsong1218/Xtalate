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
      ["Convert", "/convert"],
      ["Formats", "/formats"],
      ["History", "/history"],
      ["Docs", "/docs"],
    ];
    for (const [label, href] of expected) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
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
