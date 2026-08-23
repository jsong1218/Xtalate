# Xtalate v1.4.0 — Release Notes

> **Status: draft.** Prepared at the M53 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.4.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step,
> taken after the v1.4 architectural review (D64).

Schema version: 1.0.0

**Package `1.4.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release ships **no schema change** — the QE formats declare their conventions and the two new
formats add zero scenarios — so the mandatory `Schema version:` line above reads `1.0.0`, not
`1.4.0`. A schema number that incremented without a schema change would be a version that lies;
the honest statement is a package bump on a frozen schema.

## What's new in 1.4.0

- **The Quantum ESPRESSO pw.x pair — one full read+write format and one read-only output format
  (M50–M53).** QE joins the format family as the third dominant periodic-DFT ecosystem for MLIP
  reference data. `qe_pw_in` (the pw.x **input** — the namelist + card grammar that defines a QE
  calculation) is **full read+write**: it appears read **and** write in `xtalate capabilities`,
  `convert --to qe_pw_in` is a real conversion (the extXYZ → QE relabeling-setup arrow, with an
  honest-incompleteness warning naming exactly what physics — plane-wave cutoff, k-points,
  pseudopotential files — you must still supply before pw.x will run, never invented for you), and
  it enrols in the nightly round-trip matrix as a source **and** target. `qe_pw_out` (the pw.x
  **output**) is a **read-only output** format joining the VASP read-only class: parser-only via
  the source-never-target seam, so there is no `convert --to qe_pw_out` — the flagship MLIP
  conversion reads a pw.x run into a **label-complete extXYZ training file**
  (`xtalate convert pw.out --to extxyz`): per-frame energy (Ry → eV), per-atom forces
  (Ry/bohr → eV/Å), tension-positive stress (QE prints compression-positive; the sign is mapped
  from QE's own constants, never assumed), and per-step cells from each `CELL_PARAMETERS` card in
  a variable-cell run. Both readers tolerate the QE 6.x ↔ 7.x layout drift, refuse an unrecognized
  layout rather than partial-parsing it, read an unconverged SCF's energy present-with-value and
  flag it (`QEOUT_UNCONVERGED`), and recover a torn tail from a killed run only under the explicit
  `truncate_corrupt_tail` preset. The pair's central honesty guard: the input and output parsers
  are two readers of one run and must **agree** on its cell / species / positions (the input-echo
  cross-check, machine-checked) — a silent unit or sign disagreement is exactly the bug that
  poisons a training set at scale.
- **The roadmap §5 stopping point.** The three dominant periodic-DFT ecosystems for MLIP reference
  data — VASP (v1.2), Quantum ESPRESSO (v1.4), and CP2K (via first-party-or-plugin) — now flow
  into label-complete canonical objects. **CP2K's actual disposition is stated honestly:** it ships
  as the **advertised community-plugin handoff** — a "CP2K plugin wanted" call pointing at the
  frozen SDK seam (`xtalate.parsers` / `xtalate.exporters` entry points + the stable base classes;
  no core change needed out-of-tree), the reference plugin as template, the v1.2–v1.4 parser
  families as three worked examples (structured input / log output / input-output pairing), and a
  named maintainer-review commitment — the first test of the post-1.0 contributor model, **not** an
  in-tree parser. In-tree CP2K, if ever wanted, is a new milestone.
- **The DFT-relabel loop closes.** Production frames → re-label with DFT (QE or VASP) →
  label-complete canonical training data: the QE pair joins the read-only VASP-output formats and
  the full read+write LAMMPS pair in the README's scope statement, and the add-a-format guide gains
  the "structured input + log output" pairing worked variant (the QE pattern — structured grammar
  input, version-drifting log output, proven to agree by the input-echo cross-check).
- **Real-world hardening as a hybrid corpus (M53).** The real-world test corpus admits the QE pw.x
  pair under two existing oracles: `qe_pw_in` joins the **round-trip self-consistency** check (a
  full read+write format — parse, re-export, re-parse, assert scientifically equal) and a
  `qe_pw_in`↔`qe_pw_out` pair asserts the **input-echo agreement** on the shared initial structure.
  An authored-realistic batch spans QE 6.x + 7.x across SCF / ionic relax / vc-relax (per-step
  cells) / MD, an unconverged run, a killed run (refused, then recovered under the explicit
  preset), decorated species labels, two nonzero-`ibrav` inputs, and a carried-payload input —
  every file parses clean-or-flagged with zero silent anomalies. Batch 1 is self-authored
  (Apache-2.0, each fixture generalizing a committed golden's known-good bytes); **real
  community-contributed QE pw.x files are welcome** into the same harness (developer guide §5.7).
  The release is honest about provenance: batch 1 is **authored-realistic breadth across QE
  6.x/7.x with a standing call for real-world contributions**, not "validated against real wild
  files."

## What stays deferred

- **CP2K in-tree** — not this release (see above); a new milestone (M54+/v1.4.1) if the maintainer
  ever wants it.
- **The v1.4 architectural review** — a separate pass after this milestone and before the tag (D64),
  per the arch-review-folds-into-its-own-version rule.
- **Anything from v1.5+** — batch operations, ASE `.db`, DeePMD npy, pymatgen adapters, and the
  variable-N trajectory work remain future milestones.
