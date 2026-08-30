/**
 * The Mol\\* plugin mount (v1.6 M59-S2, extended M61-S1): renders a canonical-geometry structure
 * inside a target DOM element. Client-only by construction — this module is only ever loaded
 * through the viewer's SSR-safe dynamic import (it pulls the WebGL plugin).
 *
 * The display is deliberately **atoms-only**: the representation added is `spacefill` (no bond
 * visual), so Mol\\*'s lazy distance heuristic is never drawn — bonds are a display heuristic,
 * off by default, and any enabled bonds view carries the badge in `StructureViewer` (D234). The
 * unit cell is shown when the source carried one; a cell-less source draws no box (P3).
 *
 * **M61-S1 adds the imperative frame API** (D236): the mount builds a Mol\\* trajectory from the
 * *window* of frames the scrubber hands it (bounded — never the whole trajectory) and,
 * within that window, sets the visible frame by updating `ModelFromTrajectory`'s `modelIndex`
 * (a cheap in-place transform update — re-applying the transform with the new index, not a
 * trajectory rebuild — so scrubbing inside a window never rebuilds the trajectory). The per-frame
 * unit cell is honoured deliverable 3: on a frame
 * change the wireframe is re-created for **that frame's** model (a variable-cell trajectory
 * breathes; a cell-less frame draws no box — the `data-unitcell-drawn` render proof stays honest
 * per displayed frame). A window *change* (new frame set) is handled by the caller re-mounting; the
 * mount's `frame_index_base` maps an absolute report index to a window-local model index with no
 * arithmetic on positions.
 */
import type { Camera } from "molstar/lib/mol-canvas3d/camera.js";
import { PluginContext } from "molstar/lib/mol-plugin/context.js";
import { DefaultPluginSpec } from "molstar/lib/mol-plugin/spec.js";
import { PluginCommands } from "molstar/lib/mol-plugin/commands.js";
import { PluginStateObject as SO } from "molstar/lib/mol-plugin-state/objects.js";
import { PluginStateTransform } from "molstar/lib/mol-plugin-state/objects.js";
import { ParamDefinition as PD } from "molstar/lib/mol-util/param-definition.js";
import { Color } from "molstar/lib/mol-util/color/color.js";
import { UnitcellParams } from "molstar/lib/mol-repr/shape/model/unitcell.js";
import { Task } from "molstar/lib/mol-task/index.js";
import { geometryToTrajectory, latticeIsRenderable } from "./molstarLoader";
import type { CanonicalGeometry } from "./useGeometry";

/**
 * The state transform that turns the canonical geometry JSON into a Mol\\* trajectory cell —
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
 * The ordinary unit-cell wireframe color — a neutral slate bound to the app's chrome token, chosen
 * so the box is never confused with any §4 loss hue (in particular the supplied-violet). Mol*'s
 * stock unit-cell default is orange.
 */
const UNITCELL_COLOR = Color(0x475569);

/**
 * The supplied-violet wireframe color (v1.6 M60-S3, D235): the ◆ `text-cb-assumption` token
 * (`--cb-assumption: #6d28d9`) — the same violet the reports use for supplied/assumptions, so a
 * fabricated lattice looks different from a source lattice everywhere it appears.
 */
const SUPPLIED_CELL_COLOR = Color(0x6d28d9);

/**
 * The imperative handle the mount returns — the viewer drives frames with it (M61-S1, D236). The
 * mount owns the current bounded window's trajectory; a scrub *within* the window is a cheap
 * {@link MountedStructureViewer.setFrame}, and a *window change* is a
 * {@link MountedStructureViewer.setWindow} that rebuilds only the trajectory subtree **in place** —
 * the plugin, canvas, and camera survive, so continuous playback across window boundaries neither
 * flashes nor loses the viewer's rotation/zoom (M61 review #2).
 */
export interface MountedStructureViewer {
  /**
   * Display the window frame at the given **absolute** report index. Only indices inside the
   * mounted window are meaningful (the caller clamps); the mount maps to the window-local model
   * index from its `frame_index_base` and redraws that frame's unit-cell wireframe.
   */
  setFrame(absoluteIndex: number): Promise<void>;
  /**
   * Swap the displayed window to a new bounded frame set (the next sliding window), then show
   * `absoluteIndex` within it. Deletes and rebuilds the trajectory subtree **without** disposing the
   * plugin or resetting the camera — the user's view is preserved across the boundary. Calls
   * serialize, so a burst of window changes applies in order and the last one wins.
   */
  setWindow(geometry: CanonicalGeometry, absoluteIndex: number): Promise<void>;
  /** Dispose the plugin instance. Idempotent. */
  dispose(): void;
  /**
   * The camera get/set/observe seam (M62-S1, D239): lets the Compare tab lock the two viewers'
   * cameras together. Reading and applying a snapshot is lossless over the plugin's own state — it
   * is the {@link Camera.Snapshot} the canvas already uses — and `onChange` fires when *this*
   * viewer's camera mutates (including direct user orbit-control drags), which is the signal the
   * broadcast listens to. The Compare tab holds one of these per side and reads one to push the
   * other, guarded against the re-entrant echo (an "applying remote camera" flag).
   */
  camera: StructureViewerCamera;
}

/**
 * The camera-lock seam on one viewer (M62-S1, D239). A thin wrapper over the live plugin camera:
 * `getSnapshot`/`setSnapshot` round-trip the exact `Camera.Snapshot` object the plugin owns, and
 * `onChange` subscribes to `camera.changed` — which fires on any view/projection mutation,
 * including direct control drags — returning an unsubscribe.
 */
export interface StructureViewerCamera {
  /** Read the current camera snapshot (the plugin's own state). */
  getSnapshot(): Camera.Snapshot;
  /** Apply a camera snapshot, e.g. one read from the sibling viewer (camera-lock broadcast). */
  setSnapshot(snapshot: Camera.Snapshot): void;
  /** Subscribe to this viewer's camera changes; returns an unsubscribe. */
  onChange(listener: () => void): () => void;
}

export interface MountStructureViewerOptions {
  /** When true, the unit-cell wireframe is drawn in the supplied-violet (D235). */
  suppliedCell?: boolean;
  /**
   * The absolute report index to display initially (defaults to `geometry.frame_index_base`).
   * Only meaningful when the mounted geometry carries multiple frames.
   */
  initialFrameIndex?: number;
}

/** The unit-cell params: full defaults + the ordinary/supplied color (D235). */
function unitcellParamsFor(suppliedCell: boolean) {
  const cellColor = suppliedCell ? SUPPLIED_CELL_COLOR : UNITCELL_COLOR;
  return { ...PD.getDefaultValues(UnitcellParams), cellColor };
}

/**
 * Mount an embedded Mol\\* view of the geometry into `target` (which must be positioned).
 * Returns the imperative frame handle (see {@link MountedStructureViewer}).
 */
export async function mountStructureViewer(
  target: HTMLDivElement,
  geometry: CanonicalGeometry,
  options: MountStructureViewerOptions = {}
): Promise<MountedStructureViewer> {
  const plugin = new PluginContext(DefaultPluginSpec());
  await plugin.init();
  await plugin.mountAsync(target, {});

  let disposed = false;
  let unitcellCell: { ref: unknown } | undefined;
  // The window currently displayed and its absolute base — both mutable: `setWindow` swaps the
  // frame set in place, so every closure below reads the *current* window, never the mount-time one.
  let windowGeometry = geometry;
  let frameIndexBase = windowGeometry.frame_index_base ?? 0;

  /**
   * Build the trajectory subtree for `geo` — the trajectory (the window's frames), the default
   * preset (model + structure + component), and the atoms-only representation — and return the
   * trajectory selector (so a window swap can delete exactly this subtree). No camera reset here;
   * the caller decides whether the camera is fit (only the initial mount does).
   */
  async function buildStructure(geo: CanonicalGeometry) {
    const trajectory = await plugin.state.data
      .build()
      .to(plugin.state.data.root)
      .apply(GeometryTrajectory, { json: JSON.stringify(geo) })
      .commit({ revertOnError: true });

    await plugin.builders.structure.hierarchy.applyPreset(trajectory, "default", {
      representationPreset: "empty",
    });

    const structure = plugin.managers.structure.hierarchy.current.structures[0];
    if (structure) {
      await plugin.builders.structure.representation.addRepresentation(
        structure.cell,
        ATOMS_ONLY_REPRESENTATION
      );
    }
    return trajectory;
  }

  // The M59/M60 mount: build the initial window's structure. `setWindow` rebuilds this subtree.
  let trajectorySelector = await buildStructure(windowGeometry);

  // The initial displayed frame (the geometry endpoint serves the object's whole `frame_count`,
  // so a multi-frame window carries them all; the preset shows frame base by default).
  const initial = options.initialFrameIndex ?? frameIndexBase;

  /**
   * The `SO.Molecule.Model` cell currently driving the display, resolved **fresh** from the
   * hierarchy manager. Re-applying `ModelFromTrajectory` (a frame change) produces a new cell,
   * so any reference captured at mount goes stale.
   */
  function resolveModelCell() {
    return plugin.managers.structure.hierarchy.current.models[0]?.cell;
  }

  /**
   * Whether the displayed frame declares a renderable cell — decided by the loader's own
   * {@link latticeIsRenderable} (`cellFromLattice(...) !== undefined`), the **single source of
   * truth** for cell presence, so this gate can never disagree with the cell the loader built into
   * the model. This is the honest per-frame presence decision: Mol*'s per-frame model **inherits the
   * topology model's symmetry** when its own frame declares no cell (the trajectory spread carries
   * the static property), so the box presence must be decided from the frame the source actually
   * declared — never a fabricated box.
   */
  function frameHasRenderableCell(absoluteIndex: number): boolean {
    const localIndex = Math.max(0, absoluteIndex - frameIndexBase);
    return latticeIsRenderable(windowGeometry.frames?.[localIndex]?.cell);
  }

  /**
   * (Re)create the unit-cell wireframe for the displayed frame; returns whether a box was drawn.
   * A frame that declares no cell draws **no box** (P3, decided from the frame's canonical cell);
   * a celled frame's box is drawn by `tryCreateUnitcell` against the resolved model (whose sym
   * for a celled frame is that frame's own lattice).
   */
  async function drawUnitcellForFrame(absoluteIndex: number): Promise<boolean> {
    if (disposed) return false;
    if (unitcellCell) {
      await plugin.state.data.build().delete(unitcellCell.ref as never).commit();
      unitcellCell = undefined;
    }
    if (!frameHasRenderableCell(absoluteIndex)) {
      return false; // absence renders as absence — no box, ever (P3)
    }
    const modelCell = resolveModelCell();
    if (!modelCell) return false;
    const unitcell = await plugin.builders.structure.tryCreateUnitcell(
      modelCell,
      unitcellParamsFor(Boolean(options.suppliedCell)),
      { isHidden: false }
    );
    unitcellCell = unitcell ?? undefined;
    return Boolean(unitcell);
  }

  // The imperative frame set (M61-S1): within the mounted window, update `ModelFromTrajectory`'s
  // `modelIndex` (re-applying the transform with the new index), then redraw that frame's unit
  // cell. This is an in-place update of the existing transform, not a trajectory rebuild, so
  // scrubbing inside a window is cheap.
  async function setFrame(absoluteIndex: number): Promise<void> {
    if (disposed) return;
    const modelCell = resolveModelCell();
    if (!modelCell) return;
    const localIndex = Math.max(0, absoluteIndex - frameIndexBase);
    await plugin.state.data
      .build()
      .to(modelCell)
      .update({ modelIndex: localIndex })
      .commit();
    const drawn = await drawUnitcellForFrame(absoluteIndex);
    // The render-level proof stays honest per displayed frame (deliverable 3).
    target.dataset.unitcellDrawn = drawn ? "true" : "false";
    target.dataset.currentFrame = String(absoluteIndex);
  }

  // The imperative window swap (M61 review #2): replace the displayed frame set without disposing
  // the plugin or resetting the camera. Delete the old trajectory subtree (its model/structure/
  // representation/unit-cell cascade with it), rebuild over the new window, then show the target
  // frame. Calls serialize on `windowChain` so a burst of boundary crossings applies in order.
  let windowChain: Promise<void> = Promise.resolve();
  async function doSetWindow(newGeometry: CanonicalGeometry, absoluteIndex: number): Promise<void> {
    if (disposed) return;
    // The unit-cell ref belongs to the subtree we are about to delete; drop it before the delete so
    // `drawUnitcellForFrame` does not try to remove a stale ref after the rebuild.
    unitcellCell = undefined;
    if (trajectorySelector) {
      await plugin.state.data.build().delete(trajectorySelector.ref).commit();
    }
    windowGeometry = newGeometry;
    frameIndexBase = newGeometry.frame_index_base ?? 0;
    trajectorySelector = await buildStructure(newGeometry);
    // No Camera.Reset: the camera is deliberately preserved across a window boundary.
    await setFrame(absoluteIndex);
  }
  function setWindow(newGeometry: CanonicalGeometry, absoluteIndex: number): Promise<void> {
    windowChain = windowChain
      .then(() => doSetWindow(newGeometry, absoluteIndex))
      .catch((err) => {
        // A failed swap must not wedge the chain; log and let the next window apply.
        console.error("Mol* setWindow failed:", err);
      });
    return windowChain;
  }

  // Initial render: apply the starting frame + its cell wireframe, and expose the render proofs
  // the e2e asserts against — mounted = the canvas is live, atoms = the declared atom count,
  // current-frame/unitcell-drawn = what is actually displayed. `setFrame` draws the frame's cell
  // and sets `unitcellDrawn`, so it is the sole owner of that proof (no separate init draw); the
  // default below keeps the proof present-and-honest if `setFrame` bails before drawing.
  target.dataset.unitcellDrawn = "false";
  try {
    await setFrame(initial);
  } catch {
    // A failed initial frame/unitcell draw must not fail the structure render; presence stays false.
    target.dataset.unitcellDrawn = "false";
  }
  // Fit the camera once, on the initial mount only — window swaps preserve the user's view.
  PluginCommands.Camera.Reset(plugin);

  // The camera get/set/observe seam (M62-S1, D239): `plugin.canvas3d.camera` is guaranteed after
  // `mountAsync`. Reading/applying the `Camera.Snapshot` round-trips the plugin's own state (a
  // camera-lock broadcast is lossless), and `camera.changed` fires on any view/projection
  // mutation, including direct user orbit-control drags — the signal the Compare tab's broadcast
  // listens to. The same subscription mirrors a position/target fingerprint onto `data-camera-*`
  // so the e2e can assert two locked viewers track each other without touching the WebGL canvas.
  const pluginCamera = plugin.canvas3d!.camera;
  const cameraSeam: StructureViewerCamera = {
    getSnapshot: () => pluginCamera.getSnapshot(),
    setSnapshot: (snapshot) => {
      pluginCamera.setState(snapshot);
    },
    onChange(listener) {
      const sub = pluginCamera.changed.subscribe(() => {
        listener();
        const p = pluginCamera.getSnapshot().position;
        const t = pluginCamera.getSnapshot().target;
        target.dataset.cameraPos = `${p[0].toFixed(3)},${p[1].toFixed(3)},${p[2].toFixed(3)},${t[0].toFixed(3)},${t[1].toFixed(3)},${t[2].toFixed(3)}`;
      });
      return () => sub.unsubscribe();
    },
  };

  return {
    async setFrame(idx: number) {
      await setFrame(idx);
    },
    async setWindow(newGeometry: CanonicalGeometry, idx: number) {
      await setWindow(newGeometry, idx);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      plugin.dispose();
    },
    camera: cameraSeam,
  };
}