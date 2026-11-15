import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Kbd } from "./Kbd";

describe("Kbd", () => {
  it("renders a <kbd> in mono at the smallest UI size", () => {
    render(<Kbd>K</Kbd>);
    const kbd = screen.getByText("K");
    expect(kbd.tagName).toBe("KBD");
    expect(kbd.className).toContain("font-mono");
    expect(kbd.className).toContain("text-xs2");
  });
});
