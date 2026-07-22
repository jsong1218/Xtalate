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

## `extxyz` / `co-in-cell` (golden)

- **Source file:** `sample.extxyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M3c: a single-frame diatomic (C, O) in a cubic cell exercising the breadth of extXYZ's Properties=/Lattice= grammar. No public spec worked example exists for extXYZ (unlike XYZ §8.1 / POSCAR §8.2), so this fixture is synthetic. Values chosen to survive ASE's 8-decimal write formatting so the identity round-trip is exact.

## `poscar` / `nacl-primitive` (golden)

- **Source file:** `POSCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** MASTER_SPEC Part 2 §8.2 worked example (VASP-5 POSCAR, Direct coords, NaCl-like)

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
