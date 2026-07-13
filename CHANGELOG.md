# Changelog

All notable changes to Xtalate are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The canonical schema version is
tracked separately from the package version and reaches `1.0.0` only in the v1.0 release
(`docs/MASTER_SPEC.md` Part 2 §5); v0.1 objects carry `schema_version = "0.1.0"`.

## [Unreleased]

### Added

- **Recovery scenario catalog completion — Slice 2 (v0.2 M7).** The remaining catalog resolvers land,
  completing M7 for the four v0.1 formats.
  - **Parse-time recovery.** `missing_species` (a VASP-4 POSCAR with atom counts but no element
    symbols) and `truncate_corrupt_tail` (a trajectory with a corrupt final frame) fire before a
    Canonical Object exists; they are resolved through a new optional `ParserPlugin.parse_recover`
    hook and a `parse_with_recovery` orchestrator that re-parses under the caller's preset and threads
    the resulting Assumption into the Conversion Report. `missing_species` supports `species_map`
    (ordered symbols, `--recover missing_species=species_map,species=H:O`) and `upload_reference`;
    `truncate_corrupt_tail` supports `truncate` (keep the valid prefix) and `abort`. A recoverable
    parse error without a preset now prints an actionable hint.
  - **`upload_reference`** is offered for `missing_lattice` (and `missing_species`): the lattice or
    symbols are borrowed from a second structure named with `--recover …=upload_reference,file=PATH`,
    behind atom-count / alignment compatibility checks.
  - **`split_all`** (`frame_selection=split_all`) writes **one output file per frame** into the
    directory named by `-o`, via a new `ConversionResult.outputs`; each file is validated and the
    per-file Validation Reports are merged into one. This closes the Slice-1 cut — `frame_selection`
    now offers `split_all` wherever it triggers.
  - New: the optional `ParserPlugin.parse_recover` SDK hook (additive), `conversion.parse_with_recovery`
    / `ParseRecovery`, and `ConversionResult.outputs`. See `docs/DECISIONS.md` D38–D40.

- **Recovery scenario catalog completion (v0.2 M7, Slice 1).** The Recovery Engine, which v0.1
  shipped resolving two scenarios preset-only, now registers and hazard-classifies the **full
  MASTER_SPEC Part 4 §3.3 catalog of eight scenarios**, so classification and the honest-option-list
  rule are mechanically complete for the four v0.1 formats.
  - **`constraint_representation`** resolves with `project` (keep the target's representable
    constraint subset, e.g. POSCAR `selective_dynamics`; the unrepresentable remainder is reported
    in `removed`) or `drop_all`. Either way one Assumption is recorded and **no** field is supplied
    — the kept constraints are genuine source data (selective-reductive, never fabricative).
  - `missing_velocities`, `missing_masses`, `missing_energy`, `missing_species`, and
    `truncate_corrupt_tail` are registered and classified but honestly **refuse** in this slice —
    their resolvers land in M8 (the velocity/mass family) and v0.2 Slice 2 (the parse-time
    scenarios). `missing_energy` is deliberately optionless (no scientifically defensible synthetic
    energy exists).
  - Option lists are **computed per source/target pair**, not static: the ✳`non_periodic` option of
    `missing_lattice` is offered only for a target that can express an open cell (extXYZ, never
    POSCAR), driven by a new machine-readable `allows_open_boundaries` write-capability flag
    (`docs/DECISIONS.md` D35). (`split_all` was the Slice-1 cut line — it lands in Slice 2, above.)
  - The Recovery Engine's dispatch is now a generalized dependency-ordered resolver table
    (`frame_selection` → `constraint_representation` → `missing_lattice`), replacing the hard-coded
    two-scenario branch (`docs/DECISIONS.md` D37).

### Fixed

- **XYZ-with-comments → extXYZ no longer false-fails validation.** The extXYZ exporter writes a
  carried-through comment key (`xyz:comment`) faithfully, but the parser re-namespaced *every*
  comment key under `extxyz:`, so the value round-tripped under a changed path
  (`extxyz:xyz:comment`) and the Validation Engine's `metadata_preservation` check reported the
  planned path absent — marking every such conversion `failed`. The parser now skips the `extxyz:`
  tag for a key that already carries a `<format>:` namespace, so foreign keys round-trip verbatim
  while bare extXYZ keys are namespaced as before (`docs/DECISIONS.md` D41).

### Changed

- **A PARTIAL constraint capability now triggers recovery instead of auto-preserving.** A source
  carrying a non-empty `dynamics.constraints` list converted to a target that can represent only a
  *subset* of constraint kinds (POSCAR: `selective_dynamics`) no longer silently keeps-what-fits:
  *which* constraints survive changes the physics of a downstream relaxation, so it is now a recorded
  `constraint_representation` choice, and such a conversion **refuses without an explicit preset**.
  `NONE` capability stays ordinary bulk-reductive loss; `FULL` stays preserved; an empty
  `constraints=[]` preserves normally (`docs/DECISIONS.md` D36; `MASTER_SPEC` Revision 1.8).

---

Post-v0.1 correctness pass: eight defects found by a review that exercised the shipped code
against real inputs. Each was reproduced, fixed, and pinned with a regression test.

### Fixed

- **POSCAR/CONTCAR conversions no longer false-fail validation.** The scaling factor is now
  recorded as a `provenance` parse-note instead of `simulation.extra` (it is already folded into
  the lattice vectors, §4). Storing it in `simulation.extra` — which no exporter can carry — made
  *every* POSCAR→POSCAR/CONTCAR conversion fail `absence_conformance`, since the re-parse always
  re-derives a scale (`docs/DECISIONS.md` D34).
- **POSCAR exporter reports its element-grouping permutation** (`atom_permutation`). Any
  element-interleaved source (e.g. XYZ `H O H`) to POSCAR previously false-failed
  `species_preservation`/`positions_rmsd` as "chemistry lost" because validation compared under
  source order while the exporter had regrouped by element.
- **POSCAR coordinate-mode line now follows VASP semantics** — only `C/c/K/k` is Cartesian; every
  other line (`Direct`, `Fractional`, blank, garbage) is fractional, with an ambiguous line flagged
  (`POSCAR_AMBIGUOUS_COORDINATE_MODE`). The prior logic misread any non-`d` mode as Cartesian Å —
  silent scientific corruption.
- **Text parsers honor the error contract on non-UTF-8 input.** XYZ, extXYZ, and POSCAR now raise a
  structured `ParseError` (`*_ENCODING_ERROR`) instead of a raw `UnicodeDecodeError`.
- **extXYZ string-typed per-atom columns** (a `:S:` property such as a per-atom label) are carried
  as a JSON-scalar list instead of crashing on `astype(float)`.
- **CLI `convert --json -o PATH` writes the output file.** It previously reported success while
  silently writing nothing; the report JSON and the artifact are now independent outputs, and the
  file-write notice goes to stderr so stdout stays pure JSON.
- **Invalid `--recover` presets** exit cleanly (usage error) instead of printing a traceback.
- **POSCAR exporter rejects unrepresentable constraints** with a clear error instead of an
  `IndexError` when handed a non-`selective_dynamics` constraint.

### Changed

- **Honest-loss annotations tightened.** An extXYZ `momenta` column now records the
  "velocities converted" parse-note even when it is explicitly all-zero (a source stating the atoms
  are at rest is information, §2 rule 3), and a CONTCAR velocity tail now annotates
  `source_units["velocities"] = "angstrom/fs"` with a parse-note, rather than storing the block
  with its unit left implicit.

## [0.1.0] — 2026-07-10

First release: the complete pure-Python **library + CLI** core. It converts between four
computational-chemistry formats while reporting — and independently re-validating — every
byte of scientific information kept, dropped, or fabricated.

### Added

- **Canonical Data Model** (`xtalate.schema`) — the single internal schema every parser
  writes and every exporter reads, with the normative absence convention (`None` = "never in
  the source" vs a real zero) and an on-demand `field_presence()` introspection.
- **Plugin SDK, Format Sniffer, and Capability Matrix** (`xtalate.sdk`,
  `xtalate.discovery`, `xtalate.capabilities`) — stable parser/exporter contracts, a
  generic confidence-scored sniffer, and a per-format, per-field read/write capability registry.
- **Formats** (`xtalate.parsers`, `xtalate.exporters`) — read and write for plain **XYZ**,
  **extended XYZ** (ASE-backed, with default-laundering), **POSCAR**, and **CONTCAR**, each with a
  golden round-trip and error-fixture suite.
- **Information Discovery Engine** (`xtalate.discovery`) — the ✓/✗ Discovery Report: a file's
  canonical-field inventory annotated with the detected format's read capability.
- **Conversion Engine** (`xtalate.conversion`) — the pre-flight capability diff, the
  `write_plan` discipline (materialized as a filtered `canonical′`), the Conversion Report, and
  the completeness invariant enforced as an always-on runtime assertion.
- **Recovery Engine** (`xtalate.recovery`) — explicit, preset-only resolution of the
  `frame_selection` and `missing_lattice` scenarios under the three-way hazard model; every
  choice recorded as an Assumption, and a structured **refusal** when no choice is supplied.
- **Validation Engine** (`xtalate.validation`) — the unconditional post-conversion re-parse
  and nine-check diff (Part 5 §2) under named tolerance profiles (`default`/`strict`/`loose`),
  plus stored-report re-thresholding.
- **CLI** (`xtalate`) — `inspect`, `convert`, `validate`, and `capabilities`, with the
  CI-native exit-code contract (`0`/`2`/`3`/`4`/`5`/`1`) and `--json` structured output.

### Known limitations (v0.1 scope)

- No web service, REST API, or UI (v0.5 / v0.6).
- CIF, XDATCAR, and ASE `.traj` — the remaining Phase-1 formats — are not yet implemented (v0.2+).
- Recovery is preset-only; tolerance profiles are the three named ones (custom tables are later
  seams).

[Unreleased]: https://github.com/jsong1218/Xtalate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jsong1218/Xtalate/releases/tag/v0.1.0
