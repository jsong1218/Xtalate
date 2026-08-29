/**
 * The Mol\* plugin mount (v1.6 M59-S2): renders a canonical-geometry structure inside a target
 * DOM element. Client-only by construction — this module is only ever loaded through the viewer's
 * SSR-safe dynamic import (it pulls the WebGL plugin).
 *
 * The display is deliberately **atoms-only**: the representation added is `spacefill` (no bond
 * visual), so Mol\*'s lazy distance heuristic is never drawn — bonds are a display heuristic,
 * off by default, and any enabled bonds view carries the badge in `StructureViewer` (D234). The
 * unit cell is shown when the source carried one; a cell-less source draws no box (P3).
 */
import { PluginContext } from "molstar/lib/mol-plugin/context.js";
import { DefaultPluginSpec } from "molstar/lib/mol-plugin/spec.js";
import { PluginCommands } from "molstar/lib/mol-plugin/commands.js";
import { PluginStateObject as SO } from "molstar/lib/mol-plugin-state/objects.js";
import { PluginStateTransform } from "molstar/lib/mol-plugin-state/objects.js";
import { ParamDefinition as PD } from "molstar/lib/mol-util/param-definition.js";
import { Task } from "molstar/lib/mol-task/index.js";
import { geometryToTrajectory } from "./molstarLoader";
import type { CanonicalGeometry } from "./useGeometry";

/**
 * The state transform that turns the canonical geometry JSON into a Mol\* trajectory cell —
 * the plugin-state seam between the loader and the display pipeline (no intermediate format).
 */
const GeometryTrajectory = PluginStateTransform.BuiltIn({
  name: "geometry-trajectory",
  display: {
    name: "Canonical Geometry",
    description: "Build a trajectory from the canonical geometry JSON (M59-S2)",
  },
  from: SO.Root,
  to: SO.Molecule.Trajectory,
  params: () => ({ json: PD.Text("") }),
})({
  apply({ params }) {
    return Task.create("Build trajectory from canonical geometry", async () => {
      const geometry = JSON.parse(params.json) as CanonicalGeometry;
      const trajectory = await geometryToTrajectory(geometry);
      const description =
        trajectory.frameCount === 1
          ? undefined
          : `${trajectory.frameCount} frames`;
      return new SO.Molecule.Trajectory(trajectory, {
        label: "Structure",
        description,
      });
    });
  },
});

/** The molecules-only representation: atom spheres, no bond visual (D234). */
const ATOMS_ONLY_REPRESENTATION = {
  type: "spacefill",
  colorTheme: { name: "element-symbol" },
} as const;

/**
 * Mount an embedded Mol\* view of the geometry into `target` (which must be positioned).
 * Returns a cleanup function that disposes the plugin instance.
 */
export async function mountStructureViewer(
  target: HTMLDivElement,
  geometry: CanonicalGeometry
): Promise<() => void> {
  const plugin = new PluginContext(DefaultPluginSpec());
  await plugin.init();
  await plugin.mountAsync(target, {});

  const trajectory = await plugin.state.data
    .build()
    .to(plugin.state.data.root)
    .apply(GeometryTrajectory, { json: JSON.stringify(geometry) })
    .commit({ revertOnError: true });

  await plugin.builders.structure.hierarchy.applyPreset(trajectory, "default", {
    representationPreset: "empty",
    showUnitcell: true,
  });

  const structure = plugin.managers.structure.hierarchy.current.structures[0];
  if (structure) {
    await plugin.builders.structure.representation.addRepresentation(
      structure.cell,
      ATOMS_ONLY_REPRESENTATION
    );
  }
  PluginCommands.Camera.Reset(plugin);

  return () => {
    plugin.dispose();
  };
}
