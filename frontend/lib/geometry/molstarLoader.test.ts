/**
 * Loader tests (v1.6 M59-S2): canonical geometry JSON → Mol\* model, bonds-free, cell
 * present/absent, per-frame positions — the contract the Structure tab (M60) renders through.
 *
 * "No bonds" is asserted on the model's bond **data** (`IndexPairBonds.Provider`): Mol\* computes
 * a lazy distance heuristic at display time if a bond visual is used, but the loader attaches no
 * bond data anywhere — D234, and the viewer's atoms-only representation never triggers the
 * heuristic visual.
 */
import { describe, expect, it } from "vitest";
import type { Schemas } from "@/lib/api/client";
import {
  GeometryLoadError,
  geometryToStructure,
  geometryToTrajectory,
} from "./molstarLoader";
// Imported last: the loader's barrel anchor must evaluate the structure graph first, or the
// direct deep import can re-enter the module cycle with the symmetry registry unset.
import { ModelSymmetry } from "molstar/lib/mol-model-formats/structure/property/symmetry.js";
import { IndexPairBonds } from "molstar/lib/mol-model-formats/structure/property/bonds/index-pair.js";

type GeometryResponse = Schemas["GeometryResponse"];

/** The S1 worked-example shape: a 2-atom celled structure (species C + H, 6 Å cubic box). */
const celledFixture: GeometryResponse = {
  source: { format_id: "extxyz", filename: "worked.xyz" },
  species: ["C", "H"],
  cell: [
    [6, 0, 0],
    [0, 6, 0],
    [0, 0, 6],
  ],
  frame_index_base: 0,
  frame_count: 2,
  frames: [
    {
      index: 0,
      positions: [
        [0, 0, 0],
        [1.1, 0, 0],
      ],
      cell: [
        [6, 0, 0],
        [0, 6, 0],
        [0, 0, 6],
      ],
    },
    {
      index: 1,
      positions: [
        [0.1, 0, 0],
        [1.2, 0.05, 0],
      ],
      cell: [
        [6, 0, 0],
        [0, 6, 0],
        [0, 0, 6],
      ],
    },
  ],
};

/** The default read (no `frames` param): exactly frame 0 — the structure. */
const singleFrameFixture: GeometryResponse = {
  ...celledFixture,
  frame_count: 1,
  frames: [celledFixture.frames![0]],
};

/** The same object with no lattice anywhere — the `cell: null` case (P3). */
const cellLessFixture: GeometryResponse = {
  ...singleFrameFixture,
  cell: null,
  frames: singleFrameFixture.frames!.map((f) => ({ ...f, cell: null })),
};

describe("molstarLoader", () => {
  it("builds a structure with the declared atom count", async () => {
    const structure = await geometryToStructure(singleFrameFixture);
    expect(structure.elementCount).toBe(2);
    expect(structure.models.length).toBe(1);
  });

  it("attaches no bond data — the loader is bonds-free (D234)", async () => {
    const structure = await geometryToStructure(singleFrameFixture);
    const model = structure.models[0];
    // The loader attaches no bond data anywhere; `structure.bondCount` is *not* the assertion,
    // because Mol* computes a lazy distance heuristic there at display time if a bond visual is
    // used — the viewer's atoms-only representation (no bond visual) never triggers it.
    expect(IndexPairBonds.Provider.get(model)).toBeUndefined();
  });

  it("carries the cell for a celled source", async () => {
    const structure = await geometryToStructure(singleFrameFixture);
    const model = structure.models[0];
    const symmetry = ModelSymmetry.Provider.get(model);
    expect(symmetry).toBeDefined();
    const size = symmetry!.spacegroup.cell.size;
    expect(size[0]).toBeCloseTo(6);
    expect(size[1]).toBeCloseTo(6);
    expect(size[2]).toBeCloseTo(6);
  });

  it("loads a cell-less source with no cell object (absence renders as absence)", async () => {
    const structure = await geometryToStructure(cellLessFixture);
    const model = structure.models[0];
    expect(ModelSymmetry.Provider.get(model)).toBeUndefined();
  });

  it("projects every frame as a model in the trajectory", async () => {
    const trajectory = await geometryToTrajectory(celledFixture);
    expect(trajectory.frameCount).toBe(2);
    const structure = await geometryToStructure(celledFixture);
    expect(structure.models.length).toBe(2);
    expect(structure.elementCount).toBe(4); // 2 atoms × 2 frames
  });

  it("uses per-frame positions, not the reference frame's", async () => {
    const structure = await geometryToStructure(celledFixture);
    const frameModels = [...structure.models];
    const second = frameModels[1].atomicConformation;
    expect(second.x[1]).toBeCloseTo(1.2);
  });

  it("refuses an inconsistent frame (position count ≠ species count)", async () => {
    const bad: GeometryResponse = {
      ...singleFrameFixture,
      frames: [{ ...singleFrameFixture.frames![0], positions: [[0, 0, 0]] }],
    };
    await expect(geometryToStructure(bad)).rejects.toThrow(GeometryLoadError);
  });

  it("refuses a geometry response with no frames", async () => {
    const empty: GeometryResponse = {
      ...singleFrameFixture,
      frames: [],
    };
    await expect(geometryToStructure(empty)).rejects.toThrow(GeometryLoadError);
  });
});
