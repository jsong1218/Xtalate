import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KeyValueStrip } from "./KeyValueStrip";

describe("KeyValueStrip", () => {
  it("renders a description list with each key before its value", () => {
    render(
      <KeyValueStrip
        label="File facts"
        items={[
          { key: "atoms", value: "2", mono: true },
          { key: "frames", value: "1", mono: true },
          { key: "format", value: "POSCAR" },
        ]}
      />,
    );
    const dl = screen.getByLabelText("File facts");
    expect(dl.tagName).toBe("DL");
    expect(dl.getAttribute("aria-label")).toBe("File facts");
    const terms = within(dl).getAllByRole("term").map((t) => t.textContent);
    expect(terms).toEqual(["atoms", "frames", "format"]);
    const defs = within(dl).getAllByRole("definition").map((d) => d.textContent);
    expect(defs).toEqual(["2", "1", "POSCAR"]);
    expect(within(dl).getAllByRole("definition")[0].className).toContain("font-mono");
  });
});
