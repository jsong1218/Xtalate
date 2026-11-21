import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Wordmark } from "./Wordmark";

describe("Wordmark", () => {
  it("is a home link named exactly Xtalate, set in the serif, with a decorative mark", () => {
    render(<Wordmark />);
    const link = screen.getByRole("link", { name: "Xtalate" });
    expect(link.getAttribute("href")).toBe("/");
    expect(link.className).toContain("font-serif");
    expect(link.className).toContain("font-semibold");
    const svg = link.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
  });
});
