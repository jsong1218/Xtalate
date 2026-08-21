/**
 * "Why does this matter?" — the non-expert content layer for recovery decisions (MASTER_SPEC
 * Part 7 §3.1, deliverable 6; slice M31-S3).
 *
 * A decision card's three plain-language options are enough to *act*; this copy is what a reader
 * opens when they want to know the stakes — what the missing thing is, that a fabricated value is an
 * artifact rather than recovered data, and which choices are safe for which purposes. It is the
 * companion to `lib/mapping.ts`: mapping gives the one-line label, this gives the paragraph behind
 * the disclosure.
 *
 * Its coverage is lint-enforced (`why.coverage.test.ts`): every scenario code the engine can pause
 * on — read from the committed `docs/vocabulary.json` — must have an entry here, or CI fails. So a
 * new engine scenario (including a plugin's) surfaces as a CI failure, never as a card with no
 * "why does this matter?" for a non-expert. `frame_selection` and `missing_lattice` are the
 * flagship's own decisions and their copy is un-cuttable; the breadth beyond the v0.1-era scenarios
 * is the designated cut line — those entries stay honest but may be terse.
 */

export interface WhyThisMatters {
  /** The disclosure prompt the collapsed control reads. */
  question: string;
  /** The scientific stakes, in plain paragraphs, revealed on expand. */
  stakes: string[];
}

const QUESTION = "Why does this matter?";

/**
 * Per-scenario disclosure copy. Keyed by the engine's scenario code (`SCENARIO_HAZARD`), the same
 * key space as `SCENARIO_LABELS` in `lib/mapping.ts`.
 */
export const WHY_THIS_MATTERS: Record<string, WhyThisMatters> = {
  frame_selection: {
    question: QUESTION,
    stakes: [
      "Your file is a trajectory — a sequence of snapshots of the same atoms as they moved or relaxed over many steps. The format you are converting to holds a single structure, so exactly one of those snapshots has to be the one that is written.",
      "Every option here keeps a real frame from your file — nothing is averaged, interpolated, or invented. For a geometry relaxation the last frame is the converged structure and is the usual choice; the first frame is the starting geometry; a specific index picks a named step. Which is right depends on what you want the single structure to represent, so Xtalate asks rather than guessing.",
    ],
  },
  missing_lattice: {
    question: QUESTION,
    stakes: [
      "A simulation cell (its lattice vectors) is the periodic box the atoms live in. Your file does not define one — it may be an isolated molecule or a format that never records a cell — but the target format requires a cell to be written.",
      "A bounding box is an artifact Xtalate fabricates to satisfy the format: it wraps your atoms in a cell with some padding so the file is valid. It is not measured data and it does not describe any periodicity your source actually had. That is fine when you need a valid file for viewing or for a tool that demands a cell, but it is not a physically meaningful periodic cell for a new simulation unless you intend it as one — in which case supply the real cell yourself.",
    ],
  },
  missing_species: {
    question: QUESTION,
    stakes: [
      "Chemical symbols say which element each atom is. Your file does not carry them, and the target format cannot write atoms without knowing their identity.",
      "Assigning species is not recovering data your file lost — it is you telling Xtalate what the atoms are. Get the mapping wrong and every downstream result is wrong, so the assignment is recorded as an explicit assumption on the conversion.",
    ],
  },
  missing_masses: {
    question: QUESTION,
    stakes: [
      "Atomic masses are needed by the target but absent from your file. Filling them from a standard table (the IUPAC standard atomic weights for each element) is exact for ordinary chemistry.",
      "The filled masses are standard weights, not isotope-specific values from your system. If your work depends on a particular isotope, the standard weight is an assumption to check, not a measurement — and Xtalate records exactly which atoms were filled.",
    ],
  },
  missing_velocities: {
    question: QUESTION,
    stakes: [
      "Velocities describe how fast each atom is moving. Your file has none, and the target can carry them. Generating them (for example a Maxwell–Boltzmann sample at a temperature you choose) fabricates a fresh starting distribution — it does not reconstruct velocities your file never stored.",
      "The sample is written exactly as drawn: Xtalate does not remove centre-of-mass drift or apply any other MD-engine convenience, because that would be a silent, unrequested change. Leave such steps to the engine that runs the dynamics, and record the seed so the draw is reproducible.",
    ],
  },
  missing_energy: {
    question: QUESTION,
    stakes: [
      "A total energy value is expected by the target but missing from your file. Xtalate will not invent a number that looks like a computed result — an energy is either something your calculation produced or it is not.",
    ],
  },
  missing_required_field: {
    question: QUESTION,
    stakes: [
      "The target format requires a field your file does not contain. Supplying it is an explicit choice recorded on the conversion, never a silent default, so anyone reading the record can see the value did not come from your source.",
    ],
  },
  constraint_representation: {
    question: QUESTION,
    stakes: [
      "Fixed-atom constraints say which atoms are held in place. Formats express this differently, so writing your constraints into the target means choosing how they are represented there.",
      "The choice changes how the constraints are spelled, not which atoms are fixed — no atom becomes free or frozen that was not already. Xtalate records the representation it used so the mapping back is unambiguous.",
    ],
  },
  truncate_corrupt_tail: {
    question: QUESTION,
    stakes: [
      "The trajectory ends with frames Xtalate could not read — often a run that was interrupted mid-write. The readable frames before them are intact.",
      "Trimming drops only the unreadable tail; every frame that is kept is a frame that parsed cleanly. Nothing readable is discarded and nothing is repaired or reconstructed — the corrupt bytes are simply not carried forward.",
    ],
  },
  ambiguous_stress_convention: {
    question: QUESTION,
    stakes: [
      "Your file carries a stress tensor, but its numbers are meaningless without a sign convention: some codes write compression as positive (ASE and VASP do), others write tension as positive. The file records the values, not which convention produced them, so the same tensor can mean opposite physical states.",
      "This is not a value Xtalate invents or fills — the numbers are your file's own. What you are choosing is how to read them so they land in the canonical tension-positive convention: 'compression-positive' flips the sign, 'tension-positive' keeps it as written. Choose wrong and every stress in the output is negated, so the interpretation is recorded as an explicit assumption on the conversion rather than guessed.",
    ],
  },
  ambiguous_units: {
    question: QUESTION,
    stakes: [
      "A LAMMPS dump records bare numbers for positions and velocities but does not always state which unit style produced them. Without the style, a length of 1.0 could be one ångström (metal, real) or one metre (si), and a velocity's units differ the same way — so the numbers cannot be interpreted, or converted, until the style is fixed.",
      "This is not a value Xtalate invents — the numbers are your file's own. What you are choosing is how to read the units already written: 'metal' (ångström, picoseconds, eV), 'real' (ångström, femtoseconds, kcal/mol), or 'si' (metre, seconds, joule). Pick the wrong style and every length and velocity is off by orders of magnitude, so the choice is recorded as an explicit assumption on the conversion rather than guessed.",
    ],
  },
  ambiguous_atom_style: {
    question: QUESTION,
    stakes: [
      "A LAMMPS data file lists one row per atom, but the columns after the atom id mean different things under different atom styles — and the file does not always name the style in its Atoms section. Under 'atomic' the row is id type x y z; under 'charge' a charge column sits before the coordinates; under 'full' a molecule-id and a charge both precede them. Read the row under the wrong style and the coordinates, the charge, and the molecule assignment are all taken from the wrong columns.",
      "This is not a value Xtalate invents — the columns are your file's own. What you are choosing is how to read them: 'atomic' (id type x y z), 'charge' (id type q x y z), or 'full' (id molecule-id type q x y z). Pick the wrong style and the positions and any per-atom charge are misread, so the choice is recorded as an explicit assumption on the conversion rather than guessed.",
    ],
  },
};

/** Disclosure copy for a scenario code, or `null` when there is none (a plugin scenario). */
export function whyForScenario(code: string): WhyThisMatters | null {
  return WHY_THIS_MATTERS[code] ?? null;
}
