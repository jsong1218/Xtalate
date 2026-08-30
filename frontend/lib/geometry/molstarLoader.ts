/**
 * The canonical-geometry → Mol\* loader (v1.6 M59-S2, D233).
 *
 * Feeds Mol\* **directly from the geometry endpoint's canonical JSON** — species + positions +
 * optional cell — with **no intermediate format** between the Canonical Object and the pixels.
 * There is deliberately no export/parse-to-PDB/mmCIF/XYZ call anywhere in this module: the P1
 * rule (no hidden export in the read path) is refused by construction, and the Mol\* model is
 * built from the wire projection (`Schemas["GeometryResponse"]`) exactly as served.
 *
 * The model is built through Mol\*'s basic-schema parser path (the same seam its own XYZ loader
 * uses), so it carries **no bonds**: the Canonical Model holds none, and the loader attaches
 * none (D234 — any bond is a display heuristic, never file content). A frame's `cell` becomes a
 * Mol\* `Cell` (lengths + angles) via the standard lattice→cell conversion; a `null`/absent
 * cell stays absent (P3 — absence renders as absence, never a fabricated box).
 */
// Evaluation-order anchor: Mol*'s structure barrel must evaluate before anything touches the
// format-provider registries (`ModelSymmetry.Provider` etc.). Deep imports alone can enter the
// module cycle through the CIF-writer categories with the registry unset; the barrel pulls the
// whole structure graph in Mol*'s intended order (the same fix its own apps rely on).
import "molstar/lib/mol-model/structure.js";

import type { Schemas } from "@/lib/api/client";
import { Column, Table } from "molstar/lib/mol-data/db.js";
import { Vec3 } from "molstar/lib/mol-math/linear-algebra.js";
import { Cell } from "molstar/lib/mol-math/geometry/spacegroup/cell.js";
import { Task } from "molstar/lib/mol-task/index.js";
import type { RuntimeContext } from "molstar/lib/mol-task/execution/runtime-context.js";
import { createBasic, BasicSchema } from "molstar/lib/mol-model-formats/structure/basic/schema.js";
import { createModels } from "molstar/lib/mol-model-formats/structure/basic/parser.js";
import { ComponentBuilder } from "molstar/lib/mol-model-formats/structure/common/component.js";
import { EntityBuilder } from "molstar/lib/mol-model-formats/structure/common/entity.js";
import { Model } from "molstar/lib/mol-model/structure/model/model.js";
import { Coordinates, Frame } from "molstar/lib/mol-model/structure/coordinates.js";
import type { Trajectory } from "molstar/lib/mol-model/structure/trajectory.js";
import { Structure } from "molstar/lib/mol-model/structure/structure/structure.js";

/** The canonical geometry wire shape (generated from the S1 OpenAPI artifact). */
export type CanonicalGeometry = Schemas["GeometryResponse"];

/** Thrown when a geometry response cannot be turned into a Mol\* structure. */
export class GeometryLoadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GeometryLoadError";
  }
}

/**
 * A single Mol\* frame's coordinates: x/y/z as Float32Arrays plus the optional cell, fed
 * directly from one `GeometryFrame`'s nested-list positions.
 */
function frameFromGeometryFrame(frame: Schemas["GeometryFrame"], count: number): Frame {
  const { positions } = frame;
  if (positions.length !== count) {
    throw new GeometryLoadError(
      `Frame ${frame.index} has ${positions.length} positions but the object declares ${count} species — the geometry response is inconsistent; refusing to render a partial frame.`
    );
  }
  const x = new Float32Array(count);
  const y = new Float32Array(count);
  const z = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const p = positions[i];
    if (p.length < 3) {
      throw new GeometryLoadError(
        `Frame ${frame.index} position ${i} has ${p.length} components; the canonical array form is (N, 3).`
      );
    }
    x[i] = p[0];
    y[i] = p[1];
    z[i] = p[2];
  }
  return {
    elementCount: count,
    time: { value: frame.index, unit: "step" },
    x,
    y,
    z,
    cell: cellFromLattice(frame.cell),
    xyzOrdering: { isIdentity: true },
  };
}

/**
 * The (3, 3) lattice → Mol\* `Cell`. `null`/absent/zero-volume stays absent — a degenerate
 * box is not renderable, and absence renders as absence (P3) rather than a NaN artifact.
 *
 * This is the **single source of truth** for "does this frame declare a renderable cell": the
 * loader builds the model's cell from it, and the mount decides box-presence from it too
 * ({@link latticeIsRenderable}), so the `data-unitcell-drawn` render proof can never disagree with
 * the cell the loader actually put into the model.
 */
export function cellFromLattice(lattice: number[][] | null | undefined): Cell | undefined {
  if (!lattice || lattice.length !== 3) return undefined;
  for (const row of lattice) {
    if (row.length !== 3) return undefined;
  }
  const x = Vec3.create(lattice[0][0], lattice[0][1], lattice[0][2]);
  const y = Vec3.create(lattice[1][0], lattice[1][1], lattice[1][2]);
  const z = Vec3.create(lattice[2][0], lattice[2][1], lattice[2][2]);
  const cell = Cell.fromBasis(x, y, z);
  const zero = cell.size[0] <= 0 || cell.size[1] <= 0 || cell.size[2] <= 0;
  return zero ? undefined : cell;
}

/**
 * Whether a (3, 3) lattice yields a renderable Mol\* cell — exactly `cellFromLattice(lattice) !==
 * undefined`, so box-presence in the mount is decided by the same predicate that builds the model's
 * cell. The mount uses this for its per-frame unit-cell decision (M61-S1).
 */
export function latticeIsRenderable(lattice: number[][] | null | undefined): boolean {
  return cellFromLattice(lattice) !== undefined;
}

/**
 * The topology model: the atomic hierarchy (elements, chains, entities) from the object-level
 * `species` list, with frame 0's positions as the reference conformation. Built through Mol\*'s
 * basic-schema parser — the same seam `trajectoryFromXyz` uses — which attaches **no bonding**
 * property, so the model is bonds-free by construction.
 */
async function buildTopologyModel(
  geometry: CanonicalGeometry,
  ctx: RuntimeContext
): Promise<Model> {
  const { species } = geometry;
  const frames = geometry.frames ?? [];
  if (species.length === 0) throw new GeometryLoadError("Geometry response declares zero species.");
  if (frames.length === 0) throw new GeometryLoadError("Geometry response carries no frames.");

  const count = species.length;
  const type_symbols = new Array<string>(count);
  const id = new Int32Array(count);
  const x = new Float32Array(count);
  const y = new Float32Array(count);
  const z = new Float32Array(count);
  const first = frames[0].positions;
  if (first.length !== count) {
    throw new GeometryLoadError(
      `Frame ${frames[0].index} has ${first.length} positions but the object declares ${count} species.`
    );
  }
  for (let i = 0; i < count; i++) {
    type_symbols[i] = species[i];
    id[i] = i;
    x[i] = first[i][0];
    y[i] = first[i][1];
    z[i] = first[i][2];
  }

  const MOL = Column.ofConst("MOL", count, Column.Schema.str);
  const A = Column.ofConst("A", count, Column.Schema.str);
  const seq_id = Column.ofConst(1, count, Column.Schema.int);
  const type_symbol = Column.ofStringArray(type_symbols);
  const atom_site = Table.ofPartialColumns(BasicSchema.atom_site, {
    auth_asym_id: A,
    auth_atom_id: type_symbol,
    auth_comp_id: MOL,
    auth_seq_id: seq_id,
    Cartn_x: Column.ofFloatArray(x),
    Cartn_y: Column.ofFloatArray(y),
    Cartn_z: Column.ofFloatArray(z),
    id: Column.ofIntArray(id),
    label_asym_id: A,
    label_atom_id: type_symbol,
    label_comp_id: MOL,
    label_seq_id: seq_id,
    label_entity_id: Column.ofConst("1", count, Column.Schema.str),
    occupancy: Column.ofConst(1, count, Column.Schema.float),
    type_symbol,
    pdbx_PDB_model_num: Column.ofIntArray(new Int32Array(count)),
  }, count);

  const entityBuilder = new EntityBuilder();
  entityBuilder.setNames([["MOL", "Unknown Entity"]]);
  // `MoleculeType.Unknown` is a const enum — not readable under `isolatedModules`; its value is 0.
  entityBuilder.getEntityId("MOL", 0, "A");
  const componentBuilder = new ComponentBuilder(seq_id, type_symbol);
  componentBuilder.setNames([["MOL", "Unknown Molecule"]]);
  componentBuilder.add("MOL", 0);

  const basic = createBasic({
    entity: entityBuilder.getEntityTable(),
    chem_comp: componentBuilder.getChemCompTable(),
    atom_site,
  });
  const models = await createModels(
    basic,
    { kind: "geometry", name: "geometry", data: {} },
    ctx
  );
  if (models.frameCount === 0) throw new GeometryLoadError("Topology model construction yielded no model.");
  return models.representative;
}

/** All frames of the geometry response as Mol\* `Coordinates` (per-frame positions + optional cell). */
function coordinatesFromGeometry(geometry: CanonicalGeometry): Coordinates {
  const frames = (geometry.frames ?? []).map((f) => frameFromGeometryFrame(f, geometry.species.length));
  if (frames.length === 0) throw new GeometryLoadError("Geometry response carries no frames.");
  return Coordinates.create(frames, { value: 0, unit: "step" }, { value: 0, unit: "step" });
}

/** Build a Mol\* `Trajectory` (one model per frame) straight from the canonical geometry JSON. */
export async function geometryToTrajectory(geometry: CanonicalGeometry): Promise<Trajectory> {
  return Task.create("Build trajectory from canonical geometry", async (ctx) => {
    const model = await buildTopologyModel(geometry, ctx);
    return Model.trajectoryFromModelAndCoordinates(model, coordinatesFromGeometry(geometry));
  }).run();
}

/** Build a Mol\* `Structure` (the renderable object) straight from the canonical geometry JSON. */
export async function geometryToStructure(geometry: CanonicalGeometry): Promise<Structure> {
  return Task.create("Build structure from canonical geometry", async (ctx) => {
    const model = await buildTopologyModel(geometry, ctx);
    const trajectory = Model.trajectoryFromModelAndCoordinates(
      model,
      coordinatesFromGeometry(geometry)
    );
    return Structure.ofTrajectory(trajectory, ctx);
  }).run();
}
