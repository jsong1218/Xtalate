import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataValue } from "./DataValue";

/**
 * The mono wrapper for a rendered scientific value/count/identifier (UI redesign S1). A value is
 * always visually a number: `font-mono` from the pinned token, `text-strong` so it reads at full
 * weight on the surface. Extra `className` is layout-only and must never drop the base.
 */
describe("DataValue", () => {
  it("renders its children in the mono family with the strong text token", () => {
    render(<DataValue>10000 × 48 × 3</DataValue>);
    const el = screen.getByText("10000 × 48 × 3");
    expect(el.className).toContain("font-mono");
    expect(el.className).toContain("text-strong");
  });

  it("appends layout-only className without dropping the mono base", () => {
    render(<DataValue className="ml-2">42</DataValue>);
    const el = screen.getByText("42");
    expect(el.className).toContain("font-mono");
    expect(el.className).toContain("ml-2");
  });
});
