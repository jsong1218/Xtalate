# Changelog

All notable changes to ChemBridge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The canonical schema version is
tracked separately from the package version and reaches `1.0.0` only in the v1.0 release
(`docs/MASTER_SPEC.md` Part 2 §5); v0.1 objects carry `schema_version = "0.1.0"`.

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

[0.1.0]: https://github.com/jsong1218/ChemBridge/releases/tag/v0.1.0
