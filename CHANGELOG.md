# Changelog

All notable changes to ChemBridge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The canonical schema version is
tracked separately from the package version and reaches `1.0.0` only in the v1.0 release
(`docs/MASTER_SPEC.md` Part 2 §5); v0.1 objects carry `schema_version = "0.1.0"`.

## [Unreleased]

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

- **Canonical Data Model** (`chembridge.schema`) — the single internal schema every parser
  writes and every exporter reads, with the normative absence convention (`None` = "never in
  the source" vs a real zero) and an on-demand `field_presence()` introspection.
- **Plugin SDK, Format Sniffer, and Capability Matrix** (`chembridge.sdk`,
  `chembridge.discovery`, `chembridge.capabilities`) — stable parser/exporter contracts, a
  generic confidence-scored sniffer, and a per-format, per-field read/write capability registry.
- **Formats** (`chembridge.parsers`, `chembridge.exporters`) — read and write for plain **XYZ**,
  **extended XYZ** (ASE-backed, with default-laundering), **POSCAR**, and **CONTCAR**, each with a
  golden round-trip and error-fixture suite.
- **Information Discovery Engine** (`chembridge.discovery`) — the ✓/✗ Discovery Report: a file's
  canonical-field inventory annotated with the detected format's read capability.
- **Conversion Engine** (`chembridge.conversion`) — the pre-flight capability diff, the
  `write_plan` discipline (materialized as a filtered `canonical′`), the Conversion Report, and
  the completeness invariant enforced as an always-on runtime assertion.
- **Recovery Engine** (`chembridge.recovery`) — explicit, preset-only resolution of the
  `frame_selection` and `missing_lattice` scenarios under the three-way hazard model; every
  choice recorded as an Assumption, and a structured **refusal** when no choice is supplied.
- **Validation Engine** (`chembridge.validation`) — the unconditional post-conversion re-parse
  and nine-check diff (Part 5 §2) under named tolerance profiles (`default`/`strict`/`loose`),
  plus stored-report re-thresholding.
- **CLI** (`chembridge`) — `inspect`, `convert`, `validate`, and `capabilities`, with the
  CI-native exit-code contract (`0`/`2`/`3`/`4`/`5`/`1`) and `--json` structured output.

### Known limitations (v0.1 scope)

- No web service, REST API, or UI (v0.5 / v0.6).
- CIF, XDATCAR, and ASE `.traj` — the remaining Phase-1 formats — are not yet implemented (v0.2+).
- Recovery is preset-only; tolerance profiles are the three named ones (custom tables are later
  seams).

[Unreleased]: https://github.com/jsong1218/ChemBridge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jsong1218/ChemBridge/releases/tag/v0.1.0
