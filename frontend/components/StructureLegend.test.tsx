/**
 * StructureLegend tests (v1.6 M60-S2): the legend lists **exactly** the species present (no
 * extras, no omissions — the tested invariant), pairs every swatch with its element label as
 * text (color is never the sole carrier, Part 7 §4), and uses the exact colors Mol*'s
 * `element-symbol` theme renders with its default params — so the legend cannot drift from the
 * pixels.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ElementSymbolColors } from "molstar/lib/mol-theme/color/element-symbol.js";
import { Color, getAdjustedColorMap } from "molstar/lib/mol-util/color/color.js";
import { StructureLegend, elementColor } from "./StructureLegend";

describe("StructureLegend", () => {
  it("lists exactly the species present — no extras, no omissions", () => {
    render(<StructureLegend species={["C", "H"]} />);
    const rows = screen.getAllByTestId(/^legend-row-/);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.textContent?.trim())).toEqual(["C", "H"]);
  });

  it("dedupes repeated symbols — one row per element, never one per atom", () => {
    // The endpoint's species is per-atom, so a 3-atom H2O arrives as [O, H, H].
    render(<StructureLegend species={["O", "H", "H"]} />);
    const rows = screen.getAllByTestId(/^legend-row-/);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.textContent?.trim())).toEqual(["O", "H"]);
  });

  it("renders nothing for an empty species list", () => {
    const { container } = render(<StructureLegend species={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("pairs every swatch with its element label as text — color is never the sole carrier", () => {
    render(<StructureLegend species={["Fe", "O"]} />);
    for (const element of ["Fe", "O"]) {
      const row = screen.getByTestId(`legend-row-${element}`);
      expect(row).toHaveTextContent(element);
      const swatch = row.querySelector('[data-testid="legend-swatch"]');
      expect(swatch).not.toBeNull();
      // The swatch is decorative; the label carries the meaning.
      expect(swatch?.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("renders the exact colors Mol*'s element-symbol theme draws (default params)", () => {
    // The theme's default params are saturation 0, lightness +0.2 (the loader's viewer uses the
    // `element-symbol` theme with defaults), so the legend must apply that same adjustment.
    const rendered = getAdjustedColorMap(ElementSymbolColors, 0, 0.2);
    expect(elementColor("C")).toBe(Color.toStyle(rendered["C"] as Color));
    expect(elementColor("H")).toBe(Color.toStyle(rendered["H"] as Color));
    // Mixed-case species resolve through Mol*'s uppercase symbol table (the render's keys).
    expect(elementColor("Na")).toBe(Color.toStyle(rendered["NA"] as Color));
    expect(elementColor("Cl")).toBe(Color.toStyle(rendered["CL"] as Color));
    // The adjustment is real, not a no-op: the legend genuinely lightens the raw Jmol table.
    expect(rendered["C"]).not.toBe(ElementSymbolColors.C);
  });
});
