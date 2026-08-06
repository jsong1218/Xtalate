import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BackLink } from "./BackLink";

/**
 * The consistent back affordance (pre-M36 frontend-redesign addendum, Slice S2). Every non-landing
 * page renders one in the same place, and it navigates by route hierarchy — an explicit parent
 * destination — never raw browser-back, so a user is never trapped.
 */
describe("BackLink", () => {
  it("links to the given parent route", () => {
    render(<BackLink href="/formats" label="All formats" />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/formats");
  });

  it("names the destination for assistive tech as a back action", () => {
    render(<BackLink href="/" label="Home" />);
    // The accessible name states the action; the visible label is contained within it (WCAG 2.5.3).
    expect(screen.getByRole("link", { name: "Back to Home" })).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("marks the arrow glyph decorative so the label carries the meaning", () => {
    const { container } = render(<BackLink href="/history" label="History" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });
});
