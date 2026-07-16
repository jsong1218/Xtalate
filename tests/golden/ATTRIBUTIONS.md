<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: python tests/golden/_governance.py
     Source of truth: the per-fixture tests/golden/**/manifest.yaml files.
     CI regenerates this file and fails if it drifts (Part 8 §3.2; Part 10 §4.5). -->

# Golden-corpus attributions

Every file in the golden test corpus (`tests/golden/`) is admitted only with a license
recorded in its `manifest.yaml` (Part 8 §3.2). This file aggregates those licenses and
attributions so the obligations can never silently lapse. Synthetic, hand-authored
fixtures are the project's own work under Apache-2.0; third-party data (CC0 / CC-BY /
contributor grants) carries its source attribution here and is surfaced in the top-level
`NOTICE` file.

## `extxyz` / `co-in-cell`

- **Source file:** `sample.extxyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** Hand-authored for M3c: a single-frame diatomic (C, O) in a cubic cell exercising the breadth of extXYZ's Properties=/Lattice= grammar. No public spec worked example exists for extXYZ (unlike XYZ §8.1 / POSCAR §8.2), so this fixture is synthetic. Values chosen to survive ASE's 8-decimal write formatting so the identity round-trip is exact.

## `poscar` / `nacl-primitive`

- **Source file:** `POSCAR`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** MASTER_SPEC Part 2 §8.2 worked example (VASP-5 POSCAR, Direct coords, NaCl-like)

## `xyz` / `water-traj`

- **Source file:** `water_traj.xyz`
- **Origin:** synthetic
- **License:** Apache-2.0
- **Source:** MASTER_SPEC Part 2 §8.1 worked example (2-frame, 3-atom plain XYZ)
