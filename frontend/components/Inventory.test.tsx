import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Inventory, inventoryKind } from "./Inventory";
import type { DiscoveryReport, FieldPresenceEntry } from "@/lib/report/types";
import cifWarnings from "@/lib/discovery/__fixtures__/discovery.cif_warnings.json";
import extxyz from "@/lib/discovery/__fixtures__/discovery.extxyz.json";

/**
 * The contents inventory (MASTER_SPEC Part 3 §6, Part 7 §4). Both fixtures are real `xtalate inspect`
 * output. The CIF one is chosen because it carries all three presence states *and* three parse
 * warnings in one file, so the ○-vs-✗ distinction and the above-the-inventory warnings band are
 * asserted against genuine engine data, never a hand-built shape.
 */

const cifReport = cifWarnings as unknown as DiscoveryReport;
const extxyzReport = extxyz as unknown as DiscoveryReport;

const entry = (report: DiscoveryReport, path: string): FieldPresenceEntry => {
  const found = report.fields.find((f) => f.path === path);
  if (!found) throw new Error(`fixture missing field ${path}`);
  return found;
};

describe("inventoryKind (the ✓ / ○ / ✗-muted decision)", () => {
  it("maps a present field to preserved", () => {
    expect(inventoryKind(entry(cifReport, "atoms.symbols"))).toBe("preserved");
  });

  it("maps an absent field the format CANNOT express to absent-format (✗, muted)", () => {
    const masses = entry(cifReport, "atoms.masses");
    expect(masses.status).toBe("absent");
    expect(masses.format_capability).toBe("none");
    expect(inventoryKind(masses)).toBe("absent-format");
  });

  it("maps an absent field the format COULD express to absent-file (○)", () => {
    const charges = entry(cifReport, "electronic.charges");
    expect(charges.status).toBe("absent");
    expect(charges.format_capability).not.toBe("none");
    expect(inventoryKind(charges)).toBe("absent-file");
  });
});

describe("Inventory", () => {
  it("renders each presence state with its distinct accessible icon, not color alone", () => {
    render(<Inventory report={cifReport} />);
    const present = screen.getByTestId("inventory-atoms.symbols");
    expect(within(present).getByRole("img")).toHaveAccessibleName("Preserved");

    const cannot = screen.getByTestId("inventory-atoms.masses");
    expect(within(cannot).getByRole("img")).toHaveAccessibleName("Format cannot hold this");

    const couldHave = screen.getByTestId("inventory-electronic.charges");
    expect(within(couldHave).getByRole("img")).toHaveAccessibleName("Not in this file");
  });

  it("renders the plain-language label, never the raw canonical path", () => {
    render(<Inventory report={cifReport} />);
    const row = screen.getByTestId("inventory-cell.lattice_vectors");
    expect(within(row).getByText("Simulation cell (lattice vectors)")).toBeInTheDocument();
  });

  it("shows parse warnings in a band structurally ABOVE the inventory", () => {
    render(<Inventory report={cifReport} />);
    const warnings = screen.getByRole("region", { name: "Parse warnings" });
    const inventory = screen.getByRole("region", { name: "Contents inventory" });
    // Every warning code shows verbatim.
    expect(within(warnings).getByText("CIF_OCCUPANCY_NOT_MODELLED")).toBeInTheDocument();
    // DOM order: the warnings band precedes the inventory it qualifies.
    expect(warnings.compareDocumentPosition(inventory) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("omits the warnings band entirely for a file that parsed clean", () => {
    render(<Inventory report={extxyzReport} />);
    expect(extxyzReport.issues).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Parse warnings" })).not.toBeInTheDocument();
  });
});
