import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FormatsGrid } from "./FormatsGrid";
import type { CapabilitiesMap } from "@/lib/capabilities/types";
import withPlugin from "./__fixtures__/capabilities.with-plugin.json";
import realCaps from "@/lib/capabilities/__fixtures__/capabilities.json";

/**
 * The `/formats` grid is **generated from `GET /v1/capabilities`**, never hand-authored (slice
 * M33-S1). These tests are the P6 proof on screen: the grid is driven entirely by the fixture map,
 * so a fictional plugin format the seven built-ins do not contain renders with zero UI changes, and
 * nothing the fixture omits can appear (no hard-coded format list). The crafted fixture holds one
 * real format (Extended XYZ) and one deliberately fictional plugin (Toy Format); the real
 * seven-format fixture backs the "renders whatever the registry returns" sanity check.
 */

const plugin = withPlugin as unknown as CapabilitiesMap;
const real = realCaps as unknown as CapabilitiesMap;

describe("FormatsGrid (Part 7 §2.7, generated matrix)", () => {
  it("renders a plugin format the built-ins do not contain — the P6 payoff, zero UI changes", () => {
    render(<FormatsGrid capabilities={plugin} />);
    const row = screen.getByRole("link", { name: /Toy Format/i });
    expect(row).toBeInTheDocument();
    expect(row).toHaveAttribute("href", "/formats/toyfmt");
  });

  it("surfaces a column only the plugin declares — a plugin-only field adds a column for free", () => {
    render(<FormatsGrid capabilities={plugin} />);
    // electronic.stress is declared only by Toy Format in this fixture.
    expect(screen.getByRole("columnheader", { name: /Stress tensor/i })).toBeInTheDocument();
  });

  it("renders no format the fixture omits — there is no hard-coded format list", () => {
    render(<FormatsGrid capabilities={plugin} />);
    // The fixture has extxyz + toyfmt only; a Phase-1 built-in it omits must not appear.
    expect(screen.queryByText("VASP POSCAR")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /poscar/i })).not.toBeInTheDocument();
  });

  it("shows each declared direction's capability level as an accessible glyph", () => {
    render(<FormatsGrid capabilities={plugin} />);
    // Extended XYZ writes atoms.positions fully and holds the cell only partially.
    expect(screen.getAllByRole("img", { name: "Write Full" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("img", { name: "Write Partial" }).length).toBeGreaterThan(0);
  });

  it("renders one row per format in the registry, whatever it returns", () => {
    render(<FormatsGrid capabilities={real} />);
    for (const name of [
      "Plain XYZ",
      "Extended XYZ",
      "VASP POSCAR",
      "Crystallographic Information File",
    ]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("marks a field the format cannot express as 'None', not a blank cell", () => {
    render(<FormatsGrid capabilities={plugin} />);
    // Extended XYZ declares no stress at all → its stress cell reads 'None', never empty.
    expect(screen.getAllByRole("img", { name: "Write None" }).length).toBeGreaterThan(0);
  });
});
