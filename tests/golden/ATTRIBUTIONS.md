<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python tests/golden/_governance.py
     Source of truth: the per-fixture manifest.yaml files under tests/golden/ and tests/wild/.
     CI regenerates this file and fails if it drifts (Part 8 §3.2; Part 10 §4.5). -->

# Test-corpus attributions

Every file in the project's two test corpora — the hand-verified golden corpus
(`tests/golden/`) and the real-world corpus (`tests/wild/`, v0.4 M20) — is admitted only
with a license recorded in its `manifest.yaml` (Part 8 §3.2). This file aggregates those
licenses and attributions so the obligations can never silently lapse. Synthetic,
hand-authored fixtures are the project's own work under Apache-2.0; third-party data
(CC0 / CC-BY / contributor grants) carries its source attribution here and is surfaced in
the top-level `NOTICE` file.

Each entry is labelled with the corpus it belongs to, since the two carry different
*expectations* (a canonical JSON versus a declared issue set) but the same obligations.

## `ase_db` / `rich-key-value` (golden)

- **Source file:** `sample.db`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M55-S1 via tests/golden/ase_db/_generate.py (ASE .db SQLite container).

## `ase_db` / `single-row-labeled` (golden)

- **Source file:** `sample.db`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M55-S1 via tests/golden/ase_db/_generate.py (ASE .db SQLite container).

## `ase_traj` / `co-relax-3frame` (golden)

- **Source file:** `relax.traj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M14C via tests/golden/ase_traj/_generate.py (ASE .traj ULM container, CO molecule, 3 frames).

## `ase_traj` / `water-single-molecule` (golden)

- **Source file:** `relax.traj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M14C via tests/golden/ase_traj/_generate.py (ASE .traj ULM container, a single isolated water molecule).

## `cif` / `nacl-fm3m` (golden)

- **Source file:** `nacl_fm3m.cif`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M18; cell constant and structure from the published rock-salt structure

## `cif` / `occupancy-and-cell-uncertainty` (golden)

- **Source file:** `occupancy_cell_uncertainty.cif`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M20, promoted from the real-world corpus: the minimal file that pins the two defects the COD batch found (D71)

## `cif` / `rutile-p42mnm` (golden)

- **Source file:** `rutile_p42mnm.cif`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M18; cell and the O free parameter from the published rutile structure

## `cif` / `zno-hexagonal-p1` (golden)

- **Source file:** `zno_hexagonal.cif`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M17; hexagonal P 1 cell chosen so fractional→Cartesian is exact by hand

## `contcar` / `co-md-restart` (golden)

- **Source file:** `CONTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored CONTCAR (VASP-5 shape, Direct coords, CO diatomic) with a Cartesian velocity block

## `exfmt` / `water-monomer` (golden)

- **Source file:** `water_monomer.exfmt`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written water monomer for the xtalate-example-format reference plugin (M36).

## `extxyz` / `co-in-cell` (golden)

- **Source file:** `sample.extxyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M3c: a single-frame diatomic (C, O) in a cubic cell exercising the breadth of extXYZ's Properties=/Lattice= grammar. No public spec worked example exists for extXYZ (unlike XYZ §8.1 / POSCAR §8.2), so this fixture is synthetic. Values chosen to survive ASE's 8-decimal write formatting so the identity round-trip is exact.

## `extxyz` / `mlip-labeled-2frame` (golden)

- **Source file:** `mlip_labeled.extxyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M41: a two-frame N-O diatomic in a cubic cell carrying the three MLIP training labels — per-frame energy=, per-atom forces= column, and a non-diagonal 3x3 stress= channel — so the round-trip proof exercises all three first-class. Values are short decimals chosen to survive ASE's 8-decimal write formatting, so the interchange round-trip is exact (M40's fixture convention).

## `extxyz` / `stress6-voigt` (golden)

- **Source file:** `h2_stress6.extxyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M42-S4 (RF-4): H2 in a 4 A cubic cell carrying energy=, a per-atom forces= column, and a 6-number Voigt stress= (ASE order xx,yy,zz,yz,xz,xy) — the spelling ASE's extXYZ reader refuses outright without the parser's 6-number expansion.

## `lammps_data` / `atomic-metal-ortho` (golden)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M48-S1 (LAMMPS data parser).

## `lammps_data` / `charge-real-velocities` (golden)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M48-S1 (LAMMPS data parser).

## `lammps_data` / `full-no-style-comment` (golden)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M48-S1 (LAMMPS data parser).

## `lammps_data` / `full-triclinic-topology` (golden)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M48-S1 (LAMMPS data parser).

## `lammps_dump` / `metal-ortho-declared` (golden)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M46-S2 (LAMMPS dump parser): a two-frame trajectory in declared metal units.

## `lammps_dump` / `real-triclinic-scaled` (golden)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M46-S2 (LAMMPS dump parser): a triclinic scaled-coordinate dump in declared real units.

## `lammps_dump` / `si-ortho-declared` (golden)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M46-S2 (LAMMPS dump parser): a single-frame dump in declared si units.

## `lammps_dump` / `typed-atoms-metal` (golden)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M46-S2 (LAMMPS dump parser): a typed-atom dump in declared metal units.

## `lammps_dump` / `wrapped-flags-metal` (golden)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M46-S3 (image flags): a wrapped-coordinate dump whose second atom crosses a periodic boundary.

## `lammps_dump` / `xu-counterpart-metal` (golden)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M46-S3 (image flags): the unwrapped-coordinate counterpart of wrapped-flags-metal.

## `outcar` / `md-h2o` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M43-S1 (classical VASP 6.3.2 OUTCAR layout): md-h2o.

## `outcar` / `md-h2o-v5` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M43-S2 (classical VASP 5.4.4 OUTCAR layout): md-h2o.

## `outcar` / `npt-h2o` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M43-S1 (classical VASP 6.3.2 OUTCAR layout): npt-h2o.

## `outcar` / `npt-h2o-v5` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M43-S2 (classical VASP 5.4.4 OUTCAR layout): npt-h2o.

## `outcar` / `relax-h2o` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M43-S1 (classical VASP 6.3.2 OUTCAR layout): relax-h2o.

## `outcar` / `relax-h2o-v5` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M43-S2 (classical VASP 5.4.4 OUTCAR layout): relax-h2o.

## `outcar` / `spin-h2o` (golden)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M45-S1 (classical VASP 6.3.2 OUTCAR layout): spin-h2o.

## `poscar` / `nacl-primitive` (golden)

- **Source file:** `POSCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** MASTER_SPEC Part 2 §8.2 worked example (VASP-5 POSCAR, Direct coords, NaCl-like)

## `qe_pw_in` / `carry-kpoints` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50 (QE pw.x input parser).

## `qe_pw_in` / `decorated-labels` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50 (QE pw.x input parser).

## `qe_pw_in` / `explicit-alat-positions` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S1 (QE pw.x input parser).

## `qe_pw_in` / `explicit-angstrom` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S1 (QE pw.x input parser).

## `qe_pw_in` / `explicit-bohr-positions` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S1 (QE pw.x input parser).

## `qe_pw_in` / `explicit-crystal-positions` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S1 (QE pw.x input parser).

## `qe_pw_in` / `ibrav-12-monoclinic-b` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav1-sc` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav12-monoclinic-c` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav14-triclinic` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav2-fcc` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav3-bcc` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav4-crystal` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav4-hex` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav6-tetragonal` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_in` / `ibrav8-orthorhombic` (golden)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M50-S2 (QE pw.x input parser, ibrav expansion).

## `qe_pw_out` / `md` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `md-6x` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `relax` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `relax-6x` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `scf` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `scf-6x` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `vc-relax` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `qe_pw_out` / `vc-relax-6x` (golden)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M52-S1 (QE pw.x output parser, QE 7.x layout).

## `vasprun` / `relax-h2o` (golden)

- **Source file:** `vasprun.xml`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M42-S2 (classical VASP 6.1 layout, root <vasprun>, H2O in a 10 A cubic box, 3-ionic-step relaxation: each <calculation> carries its own <structure> with mode="direct" positions)

## `vasprun` / `scf-h2o` (golden)

- **Source file:** `vasprun.xml`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M42-S2 (classical VASP 5.4 layout, root <modeling.vasprun>, H2O in a 10 A cubic box, single-point SCF: one <calculation> with energy + forces and no per-step <structure>)

## `vasprun` / `si-npt-per-step-cell` (golden)

- **Source file:** `vasprun.xml`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M42-S2 (classical VASP 5.4 layout, root <vasprun>, Si with 2 atoms, 3-step NpT MD: each <calculation> carries its own <structure> with a growing cubic cell 5.6 -> 5.8 -> 6.0 A)

## `xdatcar` / `nacl-md-fixed-cell` (golden)

- **Source file:** `XDATCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M13 (VASP-5 XDATCAR, fixed-cell form, NaCl-like, 3 configurations)

## `xdatcar` / `si-npt-variable-cell` (golden)

- **Source file:** `XDATCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M13 (VASP-5 XDATCAR, NpT per-frame-cell form, Si, 3 configurations)

## `xdatcar` / `si-single-configuration` (golden)

- **Source file:** `XDATCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-written for M13 (VASP-5 XDATCAR, degenerate single-configuration trajectory, Si)

## `xyz` / `water-traj` (golden)

- **Source file:** `water_traj.xyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** MASTER_SPEC Part 2 §8.1 worked example (2-frame, 3-atom plain XYZ)

## `cif` / `calcium-hexaaluminate-large-expansion` (wild)

- **Source file:** `cod-1000039.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 1000039 (calcium cyclo-hexaaluminate)
- **URL:** https://www.crystallography.net/cod/1000039.cif

## `cif` / `corundum-oxidation-state-symbols` (wild)

- **Source file:** `cod-1000032.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 1000032 (corundum, Al2O3)
- **URL:** https://www.crystallography.net/cod/1000032.cif

## `cif` / `ferrocene-symbol-without-operations` (wild)

- **Source file:** `cod-2101932.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 2101932 (ferrocene, C10H10Fe)
- **URL:** https://www.crystallography.net/cod/2101932.cif

## `cif` / `fluorite-no-occupancy-column` (wild)

- **Source file:** `cod-9007064.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 9007064 (fluorite, CaF2)
- **URL:** https://www.crystallography.net/cod/9007064.cif

## `cif` / `hydrogens-declared-but-not-deposited` (wild)

- **Source file:** `cod-2100034.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 2100034
- **URL:** https://www.crystallography.net/cod/2100034.cif

## `cif` / `lithium-niobate-rhombohedral` (wild)

- **Source file:** `cod-1521772.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 1521772 (lithium niobate, LiNbO3)
- **URL:** https://www.crystallography.net/cod/1521772.cif

## `cif` / `mgo-uncertainty-parentheses` (wild)

- **Source file:** `cod-1000053.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 1000053 (periclase, MgO)
- **URL:** https://www.crystallography.net/cod/1000053.cif

## `cif` / `nacl-legacy-symmetry-tags` (wild)

- **Source file:** `cod-1000041.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 1000041 (Abrahams & Bernstein, Acta Cryst. 18, 926, 1965)
- **URL:** https://www.crystallography.net/cod/1000041.cif

## `cif` / `pyrrhotite-partial-occupancy-and-oxidation` (wild)

- **Source file:** `cod-1011179.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 1011179 (pyrrhotite, Fe(1-x)S)
- **URL:** https://www.crystallography.net/cod/1011179.cif

## `cif` / `unknown-value-markers-and-half-occupancy` (wild)

- **Source file:** `cod-4000034.cif`
- **Origin:** published-dataset
- **License:** CC0-1.0
- **Source:** Crystallography Open Database entry 4000034
- **URL:** https://www.crystallography.net/cod/4000034.cif

## `lammps_data` / `data-atomic-real-ortho` (wild)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS data file (M49-S1): an Ar-Ne mixture in the atomic atom style and real units with element-commented Masses rows and a Velocities block, generalizing the M48 golden atomic-metal-ortho's known-good bytes.

## `lammps_data` / `data-full-no-style-comment` (wild)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS data file (M49-S1): a four-ion rock-salt pair in the full column layout whose Atoms section carries no '# <style>' comment, generalizing the M48 golden full-no-style-comment's known-good bytes.

## `lammps_data` / `data-molecular-full-triclinic` (wild)

- **Source file:** `structure.data`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS data file (M49-S1): an ethane-like molecule in the full atom style (molecule-id + charges), triclinic box, with Bonds/Angles/Dihedrals/Impropers and their coefficient blocks plus Pair Coeffs, generalizing the M48 golden full-triclinic-topology's known-good bytes.

## `lammps_dump` / `dump-declared-metal-image-flags` (wild)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS dump (M49-S1): a wrapped single-snapshot metal dump whose oxygen atom has crossed the +x boundary, carrying the ix iy iz image flags that record it, generalizing the M46 golden wrapped-flags-metal.

## `lammps_dump` / `dump-declared-metal-ortho-compute` (wild)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS dump (M49-S1): a declared-metal orthogonal trajectory with velocities and open-ended compute/fix output columns, generalizing the M46 golden metal-ortho-declared's known-good bytes to the custom-column dimension.

## `lammps_dump` / `dump-declared-metal-time` (wild)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS dump (M49-S1): a declared-metal two-frame trajectory written with dump_modify time yes, so every snapshot carries an ITEM: TIME preamble (the run time in the style's time unit), element-labeled with velocities.

## `lammps_dump` / `dump-real-triclinic-typed` (wild)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS dump (M49-S1): a declared-real triclinic trajectory whose atoms are identified by numeric type only (no element column), generalizing the M46 goldens real-triclinic-scaled (tilted box) and typed-atoms-metal (type column).

## `lammps_dump` / `dump-undeclared-metal-ortho` (wild)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS dump (M49-S1): a two-frame orthogonal trajectory written without an ITEM: UNITS header (older dump output, or dump_modify units no), element-labeled with velocities, in the metal style.

## `lammps_dump` / `dump-variable-n-deposition` (wild)

- **Source file:** `dump.lammpstrj`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic LAMMPS dump (M49-S1): a three-snapshot deposition trajectory (3 -> 4 -> 4 atoms) in declared metal units — the grand-canonical/deposition shape the canonical model cannot hold — generalizing the M46 dump block spelling.

## `outcar` / `killed-truncated-v5` (wild)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic VASP 5.4.4 OUTCAR truncated mid-run (killed before the final energy summary; M45-S2).

## `outcar` / `layout-drift-v4` (wild)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic OUTCAR with a VASP 4.6.28 version banner — outside the reader's 5.x/6.x range (M45-S2).

## `outcar` / `md-npt-h2o-v5` (wild)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic VASP 5.4.4 NpT-MD OUTCAR with per-step cells (M45-S2).

## `outcar` / `relax-h2o-v6` (wild)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic VASP 6.3.2 ionic-relaxation OUTCAR, modelled on the relax-h2o golden bytes (M45-S2).

## `outcar` / `scf-h2o-v6` (wild)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic VASP 6.3.2 single-point OUTCAR, modelled on the relax-h2o golden bytes (M45-S2).

## `outcar` / `spin-h2o-v6` (wild)

- **Source file:** `OUTCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic spin-polarized VASP 6.3.2 OUTCAR (paired with spin-h2o-v6-vasprun; M45-S2).

## `qe_pw_in` / `carry-kpoints-7x` (wild)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE pw.x input carrying pseudopotential filenames + a K_POINTS card verbatim (M53-S1), generalizing the committed M50 carry-kpoints golden with spin + vdW context for realism.

## `qe_pw_in` / `decorated-labels-7x` (wild)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE pw.x input with QE-decorated ATOMIC_SPECIES labels (M53-S1), generalizing the committed M50 decorated-labels golden (Fe1 → Fe, O_vac → O) onto the 5 Å cubic cell the paired output echoes.

## `qe_pw_in` / `ibrav4-hex-mg` (wild)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE pw.x input with an ibrav = 4 (hexagonal) lattice (M53-S1), generalizing the committed M50 ibrav4-hex golden to a Mg cell with realistic A/C ratio and crystal positions.

## `qe_pw_in` / `relax-7x-h2o` (wild)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 7.x pw.x relax input (M53-S1), generalizing the committed M50 explicit-bohr-positions golden (real namelist spellings, bohr positions, alat-unit cell) to a realistic single-point relax setup with run bookkeeping (prefix/outdir/pseudo_dir/tprnfor/verbosity), cutoffs, smearing and an automatic k-point grid.

## `qe_pw_in` / `scf-6x-si-in` (wild)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE pw.x SCF input for fcc Si (M53-S1), generalizing the committed M50 ibrav2-fcc golden (ibrav = 2, A-spelling, crystal positions) to a realistic 6.x-era Si setup with run bookkeeping and an explicit band count.

## `qe_pw_in` / `unresolvable-label-7x` (wild)

- **Source file:** `pw.in`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE pw.x input whose ATOMIC_SPECIES label resolves to no element (M53-S1), authored alongside the decorated-labels-7x case to pin the refusal half of the species-label dimension.

## `qe_pw_out` / `decorated-labels-7x-out` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 7.x pw.x output echoing the decorated Fe1 / O_vac labels of the same run as decorated-labels-7x (M53-S1), generalizing the committed M52 relax golden bytes to the two-atom decorated-label run.

## `qe_pw_out` / `killed-truncated-7x-h2o` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 7.x pw.x output of a run killed mid-write (M53-S1): step 1 complete, step 2 torn inside its force table, authored by cutting a two-step known-good run at the point a scheduler kill would land (the M52-S3 truncation-shape discipline).

## `qe_pw_out` / `killed-truncated-7x-h2o-recovered` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Same bytes as killed-truncated-7x-h2o (M53-S1): the QE 7.x pw.x output of a run killed mid-write, declared here under its truncate_corrupt_tail recovery.

## `qe_pw_out` / `md-6x-h2o` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 6.x pw.x MD output (M53-S1), generalizing the committed M52 md-6x golden (v.6.8 banner, lowercase species table, G-vectors block, per-step energy/forces/stress/positions) to a three-step NVT-style run with drifting positions.

## `qe_pw_out` / `relax-7x-h2o-out` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 7.x pw.x relax output (M53-S1), generalizing the committed M52 relax golden's known-good bytes (7.x banner, species + site tables, per-step iteration / forces / stress / positions blocks) to a two-step fixed-cell relax run with varied energies and forces.

## `qe_pw_out` / `scf-6x-si-out` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 6.x pw.x SCF output for fcc Si (M53-S1), generalizing the committed M52 scf-6x golden's known-good 6.x bytes (v.6.8 banner, lowercase 'atomic species' table, the extra G-vectors diagnostic block) to the fcc Si lattice and a one-step single-point run.

## `qe_pw_out` / `unconverged-7x-h2o` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 7.x pw.x output of a run whose SCF did not converge (M53-S1), generalizing the committed M52 relax golden bytes with QE's own 'convergence NOT achieved after 100 iterations' statement in place of the achieved line.

## `qe_pw_out` / `vc-relax-7x-h2o` (wild)

- **Source file:** `pw.out`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic QE 7.x pw.x vc-relax output (M53-S1), generalizing the committed M52 vc-relax golden (per-step CELL_PARAMETERS cards) to a two-step run whose alat drifts between steps.

## `vasprun` / `spin-h2o-v6-vasprun` (wild)

- **Source file:** `vasprun.xml`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Authored-realistic spin-polarized VASP 6.3.2 vasprun.xml (paired with spin-h2o-v6; M45-S2).
