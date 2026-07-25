import { describe, expect, it } from "vitest";
import { buildPreflightPreview, capabilityPath } from "./preflight";
import type { CapabilitiesMap, FormatCapabilities } from "@/lib/capabilities/types";
import type { DiscoveryReport } from "@/lib/report/types";
import capabilitiesFixture from "@/lib/capabilities/__fixtures__/capabilities.json";
import extxyzDiscovery from "@/lib/discovery/__fixtures__/discovery.extxyz.json";
import xyzNoCellDiscovery from "@/lib/discovery/__fixtures__/discovery.xyz_nocell.json";

/**
 * The pre-flight preview intersection (MASTER_SPEC Part 3 §4.3). Every fixture here is **real engine
 * output** — `xtalate inspect --json` for the Discovery Reports, `xtalate capabilities --json` for
 * the matrix — never hand-mocked, so the client preview is checked against the exact shapes the
 * service emits and the exact write-capabilities POSCAR actually declares.
 *
 * The load-bearing cases are the two ways a wrong intersection silently diverges from the engine:
 *   (a) `cell.lattice_vectors` is a POSCAR *required* field **and present** in the extXYZ source, so
 *       it must **carry** — a naive "list every required field as needs-recovery" would misfile it;
 *   (b) `atoms.masses` is present in the source but POSCAR does not declare it, so the undeclared
 *       default (NONE) must **drop** it — a naive "not on a drop-list ⇒ carry" would promise it.
 * The no-cell source then proves presence is genuinely consulted: the *same* required lattice, now
 * absent, moves to **recover**.
 */

const matrix = capabilitiesFixture as unknown as CapabilitiesMap;
const poscarWrite = matrix.poscar.write as FormatCapabilities;
const extxyz = extxyzDiscovery as unknown as DiscoveryReport;
const xyzNoCell = xyzNoCellDiscovery as unknown as DiscoveryReport;

const paths = (items: { path: string | null }[]) => items.map((i) => i.path);

describe("buildPreflightPreview (Part 3 §4.3)", () => {
  it("carries FULL and PARTIAL source fields the target can write", () => {
    const preview = buildPreflightPreview(extxyz, poscarWrite);
    // symbols/positions/lattice are FULL, pbc is PARTIAL — all four carry.
    expect(paths(preview.carry)).toEqual(
      expect.arrayContaining([
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
        "cell.pbc",
      ]),
    );
  });

  it("surfaces the PARTIAL condition verbatim as the carried field's caveat", () => {
    const preview = buildPreflightPreview(extxyz, poscarWrite);
    const pbc = preview.carry.find((i) => i.path === "cell.pbc");
    // The exact note POSCAR declares for pbc — shown, never silently assumed to hold (D19).
    expect(pbc?.detail).toBe(poscarWrite.fields["cell.pbc"].notes);
    expect(pbc?.detail).toBeTruthy();
  });

  it("drops a source-present field the target does not declare (undeclared defaults to NONE)", () => {
    const preview = buildPreflightPreview(extxyz, poscarWrite);
    // POSCAR declares no capability for atoms.masses, forces, total_energy, charges → all drop.
    expect(paths(preview.drop)).toEqual(
      expect.arrayContaining([
        "atoms.masses",
        "dynamics.forces",
        "electronic.total_energy",
        "electronic.charges",
      ]),
    );
    // The divergence guard: masses is truly undeclared, not a declared-NONE.
    expect(poscarWrite.fields["atoms.masses"]).toBeUndefined();
    expect(paths(preview.carry)).not.toContain("atoms.masses");
  });

  it("does NOT flag a required field for recovery when it is present in the source", () => {
    const preview = buildPreflightPreview(extxyz, poscarWrite);
    expect(poscarWrite.required_fields).toContain("cell.lattice_vectors");
    // Present ⇒ carries; the required list alone must not put it in recover.
    expect(paths(preview.recover)).not.toContain("cell.lattice_vectors");
    expect(paths(preview.carry)).toContain("cell.lattice_vectors");
    expect(preview.recover).toHaveLength(0);
  });

  it("flags the SAME required field for recovery when it is absent from the source", () => {
    const preview = buildPreflightPreview(xyzNoCell, poscarWrite);
    const lattice = preview.recover.find((i) => i.path === "cell.lattice_vectors");
    expect(lattice).toBeDefined();
    expect(lattice?.scenario).toBe("missing_lattice");
    // Its present peers still carry; nothing is invented as dropped.
    expect(paths(preview.carry)).toEqual(
      expect.arrayContaining(["atoms.symbols", "atoms.positions"]),
    );
    expect(preview.drop).toHaveLength(0);
  });

  it("labels every item through the mapping table, never a raw path", () => {
    const preview = buildPreflightPreview(extxyz, poscarWrite);
    const lattice = preview.carry.find((i) => i.path === "cell.lattice_vectors");
    expect(lattice?.label).toBe("Simulation cell (lattice vectors)");
    expect(lattice?.label).not.toBe(lattice?.path);
  });
});

describe("capabilityPath", () => {
  it("strips a dynamic custom key down to its declared container", () => {
    expect(capabilityPath("user_metadata.custom_per_frame['xyz:comment']")).toBe(
      "user_metadata.custom_per_frame",
    );
    expect(capabilityPath("atoms.positions")).toBe("atoms.positions");
  });
});
