# Xtalate v1.3.0 — Release Notes

> **Status: draft.** Prepared at the M49 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.3.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step,
> taken after the v1.3 architectural review (D64).

Schema version: 1.0.0

**Package `1.3.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release ships **no schema change** — so the mandatory `Schema version:` line above reads `1.0.0`,
not `1.3.0`. A schema number that incremented without a schema change would be a version that lies;
the honest statement is a package bump on a frozen schema.

## What's new in 1.3.0

- **Two full read+write LAMMPS formats — `lammps_dump` and `lammps_data` — as a first-class
  conversion pair (M46–M48).** The first full-axis format additions since v0.3: unlike the
  read-only VASP-output class, both register a parser **and** an exporter, so each appears read
  **and** write in `xtalate capabilities` and `convert --to lammps_dump` / `--to lammps_data` are
  real conversions. Together they close the MLIP loop the VASP formats feed: **train (extXYZ) →
  deploy (`lammps_data` restart) → produce (`lammps_dump`) → relabel (extXYZ)**, every arrow a
  reported conversion. The loop-closure flagships are demonstrated end to end: `prod.dump →
  extxyz` (relabel-ready) and `relaxed.extxyz → lammps_data` (restart-ready).
- **Two never-guessed resolutions for the LAMMPS pair (M46/M48).** `ambiguous_units`
  (`metal` / `real` / `si`) — a file that declares no unit system is **refused** until the choice
  is supplied as a preset (recorded as an Assumption; a dump with a declared `ITEM: UNITS` header
  fires nothing) — and `ambiguous_atom_style` (`atomic` / `charge` / `full`) for data files. No
  default is ever guessed (**P4**), and the option lists grow only by corpus evidence, never from
  the format's documentation.
- **Honest carriage everywhere (M46–M48).** Image flags ride as a reported carry with the
  export-time unwrapping-loss prediction; `compute`/`fix` columns and the run-time step are carried
  and reported; molecular topology is carried verbatim and writes back **byte-faithfully**; a
  variable-atom-count dump is **refused with the measured per-frame counts** in the error detail —
  the recorded v2.0 groundwork for variable-N trajectories (roadmap §4).
- **The deployment format proven at 10⁴ scale (M49).** A generated 10⁴-frame dump converts to
  extXYZ **byte-identically** streamed vs. materialized inside the documented memory ceiling, and
  `parse_lammpsdump_10k` / `convert_lammpsdump_to_extxyz_10k` join the Part 8 §4 benchmark table.
  Three required engine fixes ship with the proof, each flagged to the maintainer in the record:
  the dump's timestep carry is emitted in its canonical numeric form (streamed ≡ materialized
  byte-for-byte), the dump sniffer recognises the `ITEM: UNITS` / `ITEM: TIME` preamble (Xtalate's
  own exporter output is re-sniffable), and the streamed write plan classifies per-key custom
  containers exactly as the materialized path does (a `metadata_preservation` false-fail on
  `lammps_dump → extxyz` streaming is gone).
- **Real-world hardening as a hybrid corpus (M49).** The real-world test corpus admits the two
  LAMMPS formats under a **round-trip self-consistency oracle** — a file that parses cleanly is
  re-exported through its own exporter, re-parsed, and the two canonical objects must agree — with
  an authored-realistic batch spanning metal/real units, ortho + triclinic boxes, typed and
  element-labeled atoms, compute columns, declared `ITEM: UNITS`, image flags, molecular topology,
  a genuine variable-N deposition refusal, and an atom-style-absent data refusal. Batch 1 is
  self-authored (Apache-2.0); **real community-contributed LAMMPS files are welcome** into the
  same harness — see the *Contributing real-world LAMMPS files* section of the developer guide.
  The release is honest about provenance: batch 1 is **authored-realistic**, not "validated
  against real wild files."

## What stays deferred

- **Companion-file species resolution** (deriving a dump's type→element map from a sibling
  `.data` file) tracks to **v1.3.1** — typed dumps are answered today with the
  `missing_species=species_map` preset, never a guessed map.
- **Variable-atom-count trajectories** track to **v2.0** — this release ships the measured
  refusal (a variable-N dump is refused with its per-frame counts in the error detail) as the
  evidence file the v2.0 work builds on.
- **Real-world corpus contributions** are ongoing — the harness is permanent; the standing call
  invites community LAMMPS files as they arrive.

## Install

```bash
pip install xtalate                # the library + the `xtalate` CLI
pip install "xtalate[service]"     # + the FastAPI /v1 service layer
```

**Additive-minor release.** Everything a 1.2 consumer built against — the frozen schema, the Plugin
SDK, the `/v1` contract, the documented CLI flags — keeps working unchanged: the reference-plugin
compatibility canary runs green in CI as the proof, and no engine-below-schema, `/v1`, CLI, or
frontend contract changed. Existing conversion records and files written by 1.2 remain valid
(`tool_version` stamps now read `1.3.0`; `schema_version` stays `1.0.0`).
