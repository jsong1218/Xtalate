/**
 * The File Format Guide — typed editorial content for the `/formats/[format_id]` detail pages
 * (frontend redesign addendum §4.5).
 *
 * The capability grid answers *what* a format can read and write, field by field, straight off the
 * running instance's registry. This module answers the human questions a grid cannot: what the
 * format **is**, who uses it and with which tools, what it stores, and where it falls short. It is
 * deliberately **additive editorial prose**, not generated data — so it lives here as a plain typed
 * table keyed by `format_id`, never invented from the capability declaration.
 *
 * Coverage is the seven Phase-1 formats. A format with no entry — a third-party plugin — resolves
 * to `null`, and the detail page shows an honest "no extended guide" note beside the capability grid
 * rather than a fabricated blank (the P6 seam: a plugin is still fully addressable, just without
 * first-party prose). Written to be read by a newcomer and a researcher alike.
 */

export interface FormatGuide {
  /** One or two sentences: what the format is, in plain words. Doubles as the index blurb. */
  summary: string;
  /** A short paragraph of scientific/computational context — where it sits in a real workflow. */
  context: string;
  /** Typical use cases. */
  useCases: string[];
  /** Software that commonly reads or writes it. */
  commonSoftware: string[];
  /** What information it can hold (structures / cell / trajectories / forces / energies / …). */
  stores: string[];
  /** Advantages / strengths. */
  advantages: string[];
  /** Disadvantages / trade-offs. */
  disadvantages: string[];
  /** Typical workflows the format participates in. */
  workflows: string[];
  /** Important limitations a user should know before relying on it. */
  limitations: string[];
}

/**
 * Editorial guides keyed by canonical `format_id` (the same ids `GET /v1/capabilities` uses). Keys
 * must match the registry's format ids exactly so {@link formatGuide} can join the two.
 */
const FORMAT_GUIDES: Record<string, FormatGuide> = {
  xyz: {
    summary:
      "A minimal plain-text format that lists each atom's chemical symbol and Cartesian coordinates — one of the oldest and most widely supported molecular file formats.",
    context:
      "An XYZ file is an atom count, a free-form comment line, then one line per atom (element symbol and x, y, z in ångström). That simplicity makes it a near-universal way to exchange a static geometry, but it carries no periodic cell, no bonding, and no physical quantities beyond the positions themselves.",
    useCases: [
      "Sharing a single molecule or cluster geometry between programs",
      "Quick visualization of a structure",
      "Input and output for gas-phase quantum-chemistry calculations",
      "A lowest-common-denominator interchange format",
    ],
    commonSoftware: [
      "Avogadro",
      "VMD",
      "Jmol",
      "Open Babel",
      "ASE",
      "Most quantum-chemistry packages (ORCA, Gaussian, NWChem, Psi4)",
    ],
    stores: [
      "Chemical species (element symbols)",
      "Cartesian atomic positions",
      "A free-text comment / title line",
      "Multiple frames, concatenated, as a simple trajectory",
    ],
    advantages: [
      "Human-readable and trivially parsed",
      "Supported by virtually every chemistry tool",
      "Compact for small structures",
    ],
    disadvantages: [
      "No simulation cell or periodic boundary conditions",
      "No standard place for energies, forces, velocities, or charges",
      "The comment line is unstructured, so any metadata in it is not machine-readable",
    ],
    workflows: [
      "Export a geometry from one code and visualize or re-import it in another",
      "Concatenate frames to store a simple animation or optimization path",
    ],
    limitations: [
      "Cannot represent periodicity — a crystal loses its cell when written as XYZ",
      "Only structural data survives a round trip; dynamics and electronic information are dropped",
    ],
  },

  extxyz: {
    summary:
      "A backward-compatible superset of XYZ whose comment line carries structured key–value metadata, so a single plain-text file can hold a lattice, per-atom properties, and global quantities.",
    context:
      "Extended XYZ keeps XYZ's atom-count / comment / coordinates layout but promotes the comment line to a structured header: a Lattice matrix, a Properties schema naming each per-atom column, and arbitrary global key–value pairs such as energy and stress. That makes it one of the few plain-text formats able to carry periodic cells, forces, and per-atom data together — which is why it is ASE's default and the lingua franca of machine-learning-potential datasets.",
    useCases: [
      "Training and distributing machine-learning interatomic potentials",
      "Storing periodic structures together with energies and forces",
      "Interchange within the ASE ecosystem",
      "Datasets that pair geometries with computed properties",
    ],
    commonSoftware: [
      "ASE",
      "QUIP / GAP",
      "ML-potential frameworks (e.g. MACE, NequIP)",
      "OVITO",
      "i-PI",
    ],
    stores: [
      "Everything plain XYZ stores",
      "The simulation cell (Lattice) and periodic-boundary flags",
      "Per-atom properties such as forces, charges, and velocities (via the Properties schema)",
      "Global quantities such as total energy and stress",
      "Multiple frames",
    ],
    advantages: [
      "Carries periodic cell, forces, and energies while staying plain text",
      "Self-describing per-atom column schema",
      "Backward-compatible with plain-XYZ readers",
    ],
    disadvantages: [
      "The header mini-syntax is easy to get subtly wrong",
      "No single formal standard, so extensions vary between tools",
      "Verbose for very long trajectories",
    ],
    workflows: [
      "Assemble a reference dataset of structures, energies, and forces for potential fitting",
      "Round-trip periodic structures through the ASE ecosystem",
    ],
    limitations: [
      "Metadata coverage depends on the writer — fields a producer does not emit are simply absent",
      "Column and key conventions can differ between producers",
    ],
  },

  cif: {
    summary:
      "The crystallography community's standard text format for crystal structures, describing a unit cell, its symmetry, and the atoms of the asymmetric unit.",
    context:
      "CIF (the IUCr's Crystallographic Information File) is the archival standard for crystal structures. It records lattice parameters (a, b, c, α, β, γ), a space group with its symmetry operations, and the atoms of the asymmetric unit as fractional coordinates; a reader expands that asymmetric unit by the declared symmetry to obtain the full cell. It is the format of the crystal-structure databases and the expected input for many solid-state tools.",
    useCases: [
      "Depositing and retrieving crystal structures from databases (COD, ICSD, CCDC)",
      "Publishing an experimentally or computationally determined crystal structure",
      "Feeding a crystal into solid-state and DFT codes",
      "Archiving symmetry-aware structural data",
    ],
    commonSoftware: ["VESTA", "Mercury (CCDC)", "gemmi", "ASE", "pymatgen"],
    stores: [
      "The unit cell (lattice parameters)",
      "Space-group symmetry and its operations",
      "Atoms of the asymmetric unit as fractional coordinates",
      "Site occupancies and, optionally, displacement parameters",
      "Rich bibliographic and experimental metadata",
    ],
    advantages: [
      "The archival standard for crystal structures",
      "Symmetry-aware — stores the asymmetric unit compactly",
      "Carries extensive structured metadata",
    ],
    disadvantages: [
      "Symmetry handling makes parsing and writing genuinely complex",
      "No velocities, forces, or trajectories — it is a single-structure format",
      "Dialects and non-standard tags are common in real-world files",
    ],
    workflows: [
      "Download a structure from a database and convert it for a simulation code",
      "Publish a determined structure in an archival, symmetry-aware form",
    ],
    limitations: [
      "Holds a single structure, never a trajectory",
      "Symmetry is honoured only as the file declares it — a bare space-group symbol with no operations is refused rather than guessed",
      "Dynamics and electronic quantities have no place in the format",
    ],
  },

  poscar: {
    summary:
      "VASP's structure-input file: a periodic cell plus atomic positions, with element identities given by per-species counts and a species line.",
    context:
      "POSCAR describes the starting structure for a VASP calculation — a scaling factor, three lattice vectors, the number of atoms per species, a coordinate mode (Direct/fractional or Cartesian), then the positions, optionally with selective-dynamics flags. Element symbols sit on a species line in VASP 5 and later; in older files they were implied only by the companion POTCAR, so identity can be ambiguous.",
    useCases: [
      "Defining the input geometry for a VASP DFT calculation",
      "Setting up bulk cells, surfaces, and slabs",
      "Constraining atoms via selective dynamics",
    ],
    commonSoftware: ["VASP", "ASE", "pymatgen", "VESTA", "p4vasp"],
    stores: [
      "The simulation cell (scaled lattice vectors)",
      "Atomic positions (fractional or Cartesian)",
      "Atom counts per species",
      "Element symbols (VASP-5 species line)",
      "Selective-dynamics constraints",
    ],
    advantages: [
      "The native structure input for the most widely used DFT code",
      "Compact periodic-cell representation",
      "Supports per-atom motion constraints",
    ],
    disadvantages: [
      "Element identity can be missing in old (pre-VASP-5) files",
      "No energies, forces, or trajectory — structure only",
      "Atom ordering is coupled to the species-count line",
    ],
    workflows: [
      "Build or edit a cell, run a VASP relaxation, then read the relaxed cell back from CONTCAR",
      "Convert a database CIF into a POSCAR for a DFT run",
    ],
    limitations: [
      "A single structure only",
      "Species identity depends on the file being VASP-5 style or on external context",
    ],
  },

  contcar: {
    summary:
      "The file VASP writes at the end of a run — the continued, relaxed structure — identical in layout to POSCAR.",
    context:
      "CONTCAR is byte-for-byte the same format as POSCAR; VASP emits it as the final ionic configuration of a relaxation or MD step, and it can carry lattice velocities appended after the positions for MD continuation. Its role, not its syntax, is what distinguishes it: it is an output meant to be copied over POSCAR to continue a calculation.",
    useCases: [
      "Reading the relaxed geometry after a VASP optimization",
      "Continuing an MD or relaxation run (copy CONTCAR to POSCAR)",
      "Extracting the final cell of a calculation",
    ],
    commonSoftware: ["VASP", "ASE", "pymatgen", "VESTA"],
    stores: [
      "Everything POSCAR stores (cell, positions, species, constraints)",
      "Optionally, per-atom velocities for MD continuation",
    ],
    advantages: [
      "Captures the exact final configuration of a run",
      "A drop-in continuation input once renamed to POSCAR",
      "Can carry velocities for a seamless MD restart",
    ],
    disadvantages: [
      "Shares POSCAR's identity ambiguity for old files",
      "A single frame — not the full trajectory (see XDATCAR for that)",
      "Velocities are present only if the run wrote them",
    ],
    workflows: [
      "Finish a relaxation, copy CONTCAR to POSCAR, and start the next stage",
      "Read the final relaxed structure for analysis or conversion",
    ],
    limitations: [
      "One frame only — the relaxation or MD path lives in XDATCAR and OUTCAR, not here",
      "The absence of velocities is meaningful: if the run did not write them, they are simply not present",
    ],
  },

  xdatcar: {
    summary:
      "VASP's trajectory file — a sequence of ionic configurations that share one header cell, written over the course of a run.",
    context:
      "XDATCAR records the path of a VASP calculation: a single lattice header followed by successive blocks of Direct (fractional) coordinates, one block per configuration. It is the compact way to capture how a structure evolves, but it stores geometry only — energies, forces, and velocities live in other VASP outputs.",
    useCases: [
      "Storing a molecular-dynamics or relaxation trajectory from VASP",
      "Analysing structural evolution (diffusion, phase changes) over time",
      "Feeding a trajectory into visualization or post-processing",
    ],
    commonSoftware: ["VASP", "ASE", "pymatgen", "OVITO"],
    stores: [
      "The simulation cell (a shared header lattice)",
      "A sequence of frames as fractional coordinates",
      "Atom counts and species (VASP-5 style)",
    ],
    advantages: [
      "A compact multi-frame trajectory in plain text",
      "The native VASP output for structural dynamics",
      "Shares POSCAR's cell and species conventions",
    ],
    disadvantages: [
      "Geometry only — no energies, forces, or velocities",
      "The classic layout assumes a fixed cell across frames",
      "Large for long trajectories",
    ],
    workflows: [
      "Run VASP MD, then read XDATCAR to analyse or animate the trajectory",
      "Convert a trajectory into another engine's format for post-processing",
    ],
    limitations: [
      "Only positions are stored per frame; dynamics quantities live elsewhere",
      "A per-frame cell is not part of the classic layout",
    ],
  },

  ase_traj: {
    summary:
      "The Atomic Simulation Environment's native binary trajectory format — a sequence of full snapshots, each with geometry, cell, and any attached calculator results.",
    context:
      "An ASE .traj file is a binary container that serialises a list of Atoms objects: for each frame the positions, cell, and periodic-boundary flags, plus whatever the attached calculator produced (energy, forces, stress, charges). It is the workhorse of scripted ASE workflows — optimizations, MD, and NEB — because it preserves exactly what a calculation computed, frame by frame.",
    useCases: [
      "Recording an ASE optimization, MD, or NEB run",
      "Persisting geometries together with energies and forces from a calculator",
      "Restarting or post-processing an ASE workflow",
    ],
    commonSoftware: ["ASE", "Tools built on top of ASE"],
    stores: [
      "Per-frame positions, cell, and periodic-boundary flags",
      "Calculator results per frame (energy, forces, stress, charges)",
      "Multiple frames, as a full trajectory",
    ],
    advantages: [
      "Preserves the full state an ASE calculation produced",
      "Efficient binary storage of long trajectories",
      "First-class support across ASE's tooling",
    ],
    disadvantages: [
      "Binary — not human-readable and tied to the ASE ecosystem",
      "Requires ASE to read or write",
      "Which properties are present depends on the calculator that was attached",
    ],
    workflows: [
      "Run an ASE optimization writing to a .traj, then read frames back for analysis",
      "Convert a .traj into a plain-text format for tools outside ASE",
    ],
    limitations: [
      "Requires ASE to interpret the binary container",
      "Contents reflect the attached calculator — a property that is absent was never computed",
    ],
  },
};

/**
 * The editorial guide for a format, or `null` when none exists (a plugin format). The join key is
 * the canonical `format_id`; callers pair a non-null result with the capability grid, and render an
 * honest "no extended guide" note on `null` rather than fabricating prose.
 */
export function formatGuide(formatId: string): FormatGuide | null {
  return FORMAT_GUIDES[formatId] ?? null;
}
