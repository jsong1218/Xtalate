/**
 * The plain-language mapping table — MASTER_SPEC Part 7 §3.3.
 *
 * Scenario codes and canonical field paths are machine vocabulary; the UI shows a human a plain
 * label and keeps the machine code one disclosure away, so a reader with the JSON report open can
 * still match every row (§3.3). This is the **one** exported mapping for the whole app — every page
 * resolves labels through here, never inline.
 *
 * Its coverage is lint-enforced (`mapping.coverage.test.ts`): the committed `docs/vocabulary.json`,
 * exported from the engine's own registries, lists every scenario code and canonical path, and the
 * lint fails if any lacks an entry below. So a new engine scenario or a new schema field — including
 * one added by a future plugin — surfaces as a CI failure here, not as a raw code on screen.
 */

export interface Labeled {
  /** Plain-language label shown to the user. */
  label: string;
  /** Optional one-line plain-language elaboration (for tooltips / disclosures). */
  description?: string;
}

/** Recovery scenario codes (`SCENARIO_HAZARD`) → plain labels (Part 4 §3.3). */
export const SCENARIO_LABELS: Record<string, Labeled> = {
  missing_lattice: {
    label: "No simulation cell",
    description: "The target format needs lattice vectors this file does not have.",
  },
  missing_species: {
    label: "Unknown atom types",
    description: "Atom identities (chemical symbols) are missing and the target requires them.",
  },
  missing_velocities: {
    label: "Atom velocities",
    description: "The target can carry velocities; this file has none to write.",
  },
  missing_masses: {
    label: "Atom masses",
    description: "Atomic masses are missing and are needed to proceed.",
  },
  missing_energy: {
    label: "Total energy",
    description: "A total energy value is missing and the target expects one.",
  },
  missing_required_field: {
    label: "A required field is missing",
    description: "The target format requires a field this file does not contain.",
  },
  frame_selection: {
    label: "Pick which snapshot to keep",
    description: "The source is a trajectory but the target holds a single structure.",
  },
  truncate_corrupt_tail: {
    label: "Trim a corrupt trajectory tail",
    description: "The trajectory ends with unreadable frames that can be dropped.",
  },
  constraint_representation: {
    label: "How constraints are written",
    description: "The target expresses fixed-atom constraints differently from the source.",
  },
};

/** Fixed canonical field paths (`FIXED_CANONICAL_PATHS`) → plain labels (Part 2 §3). */
export const PATH_LABELS: Record<string, Labeled> = {
  "frame.time": { label: "Frame time" },
  "atoms.symbols": { label: "Chemical species (symbols)" },
  "atoms.atomic_numbers": { label: "Atomic numbers" },
  "atoms.positions": { label: "Atom positions" },
  "atoms.masses": { label: "Atom masses" },
  "cell.lattice_vectors": { label: "Simulation cell (lattice vectors)" },
  "cell.pbc": { label: "Periodic boundary conditions" },
  "cell.space_group": { label: "Space group" },
  "dynamics.velocities": { label: "Atom velocities" },
  "dynamics.forces": { label: "Forces on atoms" },
  "dynamics.constraints": { label: "Fixed-atom constraints" },
  "electronic.total_energy": { label: "Total energy" },
  "electronic.stress": { label: "Stress tensor" },
  "electronic.charges": { label: "Atomic charges" },
  "electronic.magnetic_moments": { label: "Magnetic moments" },
  "electronic.total_spin": { label: "Total spin" },
  "trajectory.timestep": { label: "Trajectory timestep" },
  "simulation.source_code": { label: "Source software" },
  "simulation.calculator": { label: "Calculator / method" },
  "simulation.xc_functional": { label: "Exchange–correlation functional" },
  "simulation.pseudopotentials": { label: "Pseudopotentials" },
  "simulation.thermostat": { label: "Thermostat" },
  "simulation.md_ensemble": { label: "MD ensemble" },
  "simulation.temperature": { label: "Temperature" },
  "simulation.extra": { label: "Other simulation settings" },
  "user_metadata.tags": { label: "Tags" },
  "user_metadata.annotations": { label: "Annotations" },
};

/**
 * Dynamic per-key categories (`CUSTOM_PATH_CATEGORIES`). A concrete inventory path such as
 * `user_metadata.custom_global['stress_eV']` resolves to its category label plus the key, so
 * arbitrary custom keys need no per-key mapping entry (Part 2 §3.10).
 */
export const CUSTOM_CATEGORY_LABELS: Record<string, Labeled> = {
  "user_metadata.custom_global": { label: "Custom global value" },
  "user_metadata.custom_per_atom": { label: "Custom per-atom value" },
  "user_metadata.custom_per_frame": { label: "Custom per-frame value" },
};

/** `user_metadata.custom_global['key']` → category prefix + key. */
const CUSTOM_PATH_RE = /^(user_metadata\.custom_(?:global|per_atom|per_frame))\['(.+)'\]$/;

/**
 * Plain label for a recovery scenario code. Unknown codes fall back to the raw code — the UI never
 * hides a token it cannot name; it shows the machine code rather than a wrong guess (and the
 * coverage lint prevents a known code from reaching this fallback).
 */
export function labelForScenario(code: string): Labeled {
  return SCENARIO_LABELS[code] ?? { label: code };
}

/**
 * Plain label for a canonical field path, resolving dynamic `custom_*['key']` paths to their
 * category label plus the key. Unknown fixed paths fall back to the raw path (see above).
 */
export function labelForPath(path: string): Labeled {
  const fixed = PATH_LABELS[path];
  if (fixed) return fixed;

  const match = CUSTOM_PATH_RE.exec(path);
  if (match) {
    const category = CUSTOM_CATEGORY_LABELS[match[1]];
    if (category) return { label: `${category.label} “${match[2]}”`, description: category.description };
  }
  return { label: path };
}
