import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppHeader } from "./AppHeader";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";

/**
 * The app-shell header (pre-M36 frontend-redesign addendum, Slice S2): a home wordmark on the left,
 * the primary nav, and the theme toggle on the right — present on every page so navigation and the
 * light/dark switch are always in the same place. The toggle needs the ThemeProvider context, so the
 * header is rendered within it here (as it is in the real tree).
 */
function renderHeader() {
  return render(
    <ThemeProvider>
      <AppHeader />
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
});
