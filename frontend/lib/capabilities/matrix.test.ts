import { describe, expect, it } from "vitest";
import { cellLevel, fieldLabel, formatRows, matrixFields } from "./matrix";
import type { CapabilitiesMap } from "./types";
import realCaps from "./__fixtures__/capabilities.json";

/**
 * The matrix helpers derive the `/formats` grid from the endpoint body alone (slice M33-S1). The
 * real seven-format fixture is genuine `xtalate capabilities --json` output; the crafted maps below
 * isolate the two rules that must hold no matter what the registry returns: a format the built-ins
 * do not contain still becomes a row, and a field only one format declares still becomes a column.
 */

const caps = realCaps as unknown as CapabilitiesMap;

describe("formatRows", () => {
  it("returns one row per format, sorted by display name, carrying both directions", () => {
    const rows = formatRows(caps);
    expect(rows.map((r) => r.format_id)).toContain("cif");
    // ASE Trajectory sorts before Crystallographic Information File by name, not by id.
    const names = rows.map((r) => r.format_name);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
    const cif = rows.find((r) => r.format_id === "cif")!;
    expect(cif.read).toBeDefined();
    expect(cif.write).toBeDefined();
    expect(cif.format_name).toBe("Crystallographic Information File");
  });

  it("makes a format a row from the data alone — a plugin the built-ins lack appears for free", () => {
    const withPlugin: CapabilitiesMap = {
      toyfmt: {
        write: {
          format_id: "toyfmt",
          format_name: "Toy Format",
          direction: "write",
          fields: { "atoms.positions": { level: "full", notes: null } },
          max_frames: 1,
          required_fields: ["atoms.positions"],
          allows_open_boundaries: true,
          representable_constraint_kinds: [],
          writable_custom_keys: {},
          writable_custom_key_pattern: {},
          native_coordinate_system: "cartesian",
          lossy_notes: [],
          numeric_precision: {},
        },
      },
    };
    const rows = formatRows(withPlugin);
    expect(rows).toHaveLength(1);
    expect(rows[0].format_id).toBe("toyfmt");
    expect(rows[0].format_name).toBe("Toy Format");
    expect(rows[0].read).toBeUndefined();
    expect(rows[0].write).toBeDefined();
  });
});

describe("matrixFields", () => {
  it("is the union of every declared field, in canonical schema order", () => {
    const fields = matrixFields(caps).map((f) => f.path);
    // Canonical order: atoms.* precede electronic.* precede user_metadata.*.
    expect(fields.indexOf("atoms.positions")).toBeLessThan(fields.indexOf("electronic.total_energy"));
    expect(fields.indexOf("electronic.total_energy")).toBeLessThan(
      fields.indexOf("user_metadata.custom_per_frame"),
    );
    // cell.space_group is declared by CIF only — the union still surfaces it as a column.
    expect(fields).toContain("cell.space_group");
  });

  it("gives every column a plain-language header, not a raw path", () => {
    const positions = matrixFields(caps).find((f) => f.path === "atoms.positions")!;
    expect(positions.label).toBe("Atom positions");
  });
});

describe("cellLevel", () => {
  it("reads a declared level straight off the field map", () => {
    const cif = formatRows(caps).find((r) => r.format_id === "cif")!;
    expect(cellLevel(cif.write, "atoms.positions")).toBe("full");
    expect(cellLevel(cif.write, "electronic.total_energy")).toBe("none");
  });

  it("defaults an undeclared field to none — the format cannot express it (Part 3 §4.3)", () => {
    const xyz = formatRows(caps).find((r) => r.format_id === "xyz")!;
    // Plain XYZ declares no cell at all; asking for the cell column is 'none', not a crash.
    expect(cellLevel(xyz.write, "cell.lattice_vectors")).toBe("none");
  });

  it("returns null for a direction the format does not declare at all", () => {
    expect(cellLevel(undefined, "atoms.positions")).toBeNull();
  });
});

describe("fieldLabel", () => {
  it("names a fixed leaf path through the shared mapping table", () => {
    expect(fieldLabel("cell.lattice_vectors")).toBe("Simulation cell (lattice vectors)");
  });

  it("names a bare custom container that labelForPath alone would leave raw", () => {
    expect(fieldLabel("user_metadata.custom_per_atom")).toBe("Custom per-atom value");
  });
});
