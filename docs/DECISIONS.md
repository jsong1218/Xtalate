# ChemBridge — Engineering Decisions Log

> **Status:** Binding for implementation, subordinate to `MASTER_SPEC.md`. This log records the concrete build-time decisions that the spec leaves to implementation — the ones `docs/ARCHITECTURE_REVIEW.md` §3/§7 flagged as needed before code. Each follows the house style: state the decision, reject at least one alternative. New decisions append here with an ID; a decision that later contradicts the spec triggers a `MASTER_SPEC.md` Revision note in the same change (standing rule, `IMPLEMENTATION_PLAN_v0.1.md` §4).

## D1 — One distribution, `src/` layout (resolves review §4.1, B4)

**Decision.** A single publishable distribution, `chembridge`, built from a `src/chembridge/` package with subpackages `schema`, `sdk`, `parsers`, `exporters`, `capabilities`, `discovery`, `conversion`, `recovery`, `validation`, `cli`. Not eight separately-versioned distributions.

**Rejected — one distribution per component** (`packages/canonical-schema/`, etc., each with its own `pyproject.toml`). Multiplies version numbers, editable-install wiring, and cross-package pinning for a solo maintainer with zero external consumers of a sub-component. The *logical* separation those directories exist for is delivered by the import-graph contract (D5), which works identically on subpackages. Splitting out (e.g. a slim `chembridge-sdk` at v1.0) stays available as an additive packaging change.

**Rejected — flat layout** (`chembridge/` at repo root, no `src/`). The `src/` layout prevents the classic "tests import the un-installed working copy instead of the installed package" footgun and makes the editable install the only import path.

**Naming refinement over `IMPLEMENTATION_PLAN_v0.1.md` M0.** The plan's shorthand listed a combined `formats/`; this log instead keeps `parsers/` and `exporters/` as separate subpackages, because the spec gives them distinct components with distinct "Must NOT" contracts (Part 1 §2) and cites `packages/parsers`/`packages/exporters` throughout. Within each, modules are organized one-per-format (`parsers/xyz.py`, `exporters/xyz.py`). Recorded as `MASTER_SPEC` Revision 1.2 addendum item 8.

## D2 — Python ≥ 3.11

**Decision.** `requires-python = ">=3.11"`.

**Rejected — ≥ 3.9/3.10.** 3.11 gives `tomllib`, faster CPython, and mature `X | None` typing without `__future__` imports; nothing in the target user base (2026 scientific Python) is pinned below it. **Rejected — ≥ 3.12 only.** Needlessly excludes 3.11, still common on HPC/lab images. CI runs 3.11; 3.12 is listed as supported.

## D3 — Build backend: Hatchling

**Decision.** `hatchling>=1.27` (PEP 639 SPDX `license`/`license-files` support).

**Rejected — setuptools.** Works, but its `src/` + PEP 639 configuration is heavier and its defaults leak (accidental package discovery). **Rejected — Flit.** Elegant for pure-Python single modules, but less ergonomic once console scripts, data files (golden corpus), and future native bits appear. Hatchling is the modern middle with minimal config.

## D4 — Dependencies

**Decision.** Core runtime: `pydantic>=2.7`, `numpy>=1.26`. Sole scientific-I/O dependency: **ASE** (added when the extXYZ parser lands, M3c — see D7), version-pinned at that point. Dev extra: `pytest`, `ruff`, `mypy`, `import-linter`.

**Rejected — adding ASE now.** It is a heavy transitive tree; nothing before M3c imports it, and keeping the M0–M3b dependency surface to pydantic+numpy keeps installs fast and the laundering-test boundary explicit. **Rejected — pymatgen as a core dep.** D7 hand-rolls POSCAR/CONTCAR, so pymatgen is not needed in v0.1 at all.

## D5 — Tooling and P2 enforcement

**Decision.** `ruff` (lint + format), `mypy --strict`, `import-linter`, `pytest` — all four run on every PR (`.github/workflows/ci.yml`) from day one, not as stubs. The import-linter `layers` contract (in `pyproject.toml`) encodes the acyclic graph of Part 1 §5.1 and is the mechanical enforcement of **P2**.

**Rejected — a hand-written import-check script / deferred "lint stub"** (as the roadmap's week 1 suggested). A real `import-linter` contract is barely more effort than a stub and actually fails CI on a violation; a stub that passes vacuously trains contributors to ignore it. **Rejected — mypy non-strict.** For a library whose product is correctness, strict typing from an empty tree costs nothing and prevents a slow slide.

## D6 — CLI framework: argparse (stdlib)

**Decision.** The `chembridge` CLI (Appendix A) is built on the standard library's `argparse`, with `chembridge.cli:main` as the console-script entry point.

**Rejected — Typer / Click.** Nicer help ergonomics, but each is a runtime dependency for a four-subcommand surface (`inspect`/`convert`/`validate`/`capabilities`) that argparse covers, and the CLI is a thin JSON presenter (Appendix A) where dependency minimalism matters more than decorator sugar. Revisit only if the surface grows substantially post-v0.1.

## D7 — Per-format implementation strategy (resolves review B5)

**Decision.** Hand-rolled **XYZ** (trivial grammar; avoids library-default laundering entirely). ASE-backed **extXYZ** with the mandatory default-laundering suite (Part 3 §2) — the `Properties=`/`Lattice=` grammar is where battle-tested code earns its keep. Hand-rolled **POSCAR/CONTCAR** (well-documented; hand-rolling gives full control of the selective-dynamics → `Constraint` mapping and avoids a pymatgen dependency). Net effect: **ASE is the only scientific dependency in v0.1**, and it backs exactly one format.

**Rejected — ASE/pymatgen behind all four formats.** Maximizes reuse but also maximizes the laundering-test burden (every library-invented default — zero cell, `pbc=(F,F,F)`, zero momenta — must be caught and nulled, Part 3 §2) and drags two heavy deps in for formats a few hundred lines of hand-rolled code handle deterministically.

## D8 — Array serialization and golden-file equality (resolves review B6)

**Decision.** NumPy arrays (float64 in memory) serialize to nested JSON lists using Python's default shortest-round-tripping float `repr` (what `json.dumps` emits). Golden-file comparison **deserializes both sides and compares arrays with exact `==`** (integers/counts) or `np.array_equal` on the parsed values — never string-compares JSON text. This makes float64 → JSON → float64 lossless and keeps the golden corpus deterministic across platforms.

**Rejected — fixed-decimal string formatting** (e.g. `%.12f`). Truncates float64 and reintroduces exactly the representational ambiguity the tolerance model (Part 5 §4) exists to reason about explicitly. **Rejected — comparing serialized text.** Whitespace/key-order/float-format differences produce false failures; equality is a property of the *values*, not their serialization.

## D9 — License: Apache-2.0 (owner decision; NOTICE added)

**Decision.** Apache-2.0, matching `MASTER_SPEC` Part 10 §4.1. The repository `LICENSE` is the Apache-2.0 text; a `NOTICE` file is the attribution home the golden-corpus policy (Part 8 §3.2) and PEP 639 `license-files` both reference.

**Context.** The prior MIT/Apache conflict (`ARCHITECTURE_REVIEW.md` A1) was resolved by the project owner in favor of Apache-2.0; this log records the resolution and the added `NOTICE`.

## D10 — Commit authorship: no AI attribution

**Decision.** Commits are authored by the human maintainer. No `Co-Authored-By: Claude`, no "Generated with Claude Code" trailer, and no AI listed as author or contributor in commit metadata, `CITATION.cff`, or release notes. Recorded in `MASTER_SPEC` (Preface, "Working conventions") so it governs every agent session that reads the spec as its brief.

## D11 — Development environment: project-local `.venv` (stdlib), not conda

**Decision.** Development uses a project-local virtual environment at `.venv/` created with the standard library (`python -m venv .venv`), then `pip install -e ".[dev]"`. `.venv/` is already gitignored and is never committed. This matches how CI provisions its environment (pip + `actions/setup-python`) and how Persona 2 consumes the project (`pip install chembridge` from PyPI, Part 9 §3).

**Rejected — conda.** The maintainer uses conda for other projects but deliberately not this one. The usual computational-chemistry reason to reach for conda is painful compiled dependencies (spglib, RDKit, MKL); ChemBridge's dependency surface is pydantic + numpy + (later) ASE — all pure-Python with reliable pip wheels, and pymatgen was rejected (D7) — so conda buys nothing here while adding environment-resolution overhead and a dev/CI toolchain split (CI is pip-based). A project-local `.venv` also shadows an active conda `base` cleanly, so the maintainer need not `conda deactivate` to work on this repo.

**Rejected (for now) — uv.** `uv` is a fine faster alternative and stays entirely in the pip/PyPI world, but it is not currently installed on the machine (adopting it means a global install first), and the speed benefit is marginal for a three-package dependency surface. `uv venv && uv pip install -e ".[dev]"` remains a drop-in swap later — it reads the same `pyproject.toml` unchanged — if install/resolve time ever becomes a friction point.

**Python version.** The `.venv` is built from the machine's available interpreter, **Python 3.13** (conda `base`); no 3.11 is installed locally, and installing one via conda would contradict this decision. Since CI pins the supported floor (3.11), the `.venv`'s 3.13 would otherwise be untested — so CI was changed to a matrix over **3.11 (floor) and 3.13 (dev)** (`.github/workflows/ci.yml`), and 3.13 was added to the `pyproject.toml` classifiers (it was already permitted by `requires-python = ">=3.11"`). Dev and CI therefore share both endpoints; the M0 gate suite passed identically on 3.13 locally and is exercised on 3.11 in CI.

## D12 — `custom_per_atom` / `custom_per_frame` accept JSON-scalar lists, not only numeric arrays (M1)

**Decision.** A `UserMetadata.custom_per_atom` / `custom_per_frame` value is a sequence whose first dimension is N / F and is **either** a numeric `float64` ndarray (extXYZ extra columns) **or** a length-N / length-F `list` of JSON scalars (per-frame/per-atom free text, e.g. XYZ comment lines). Implemented as a `left_to_right` union (`ArrayNx | list[JsonValue]`) so numeric input coerces to an ndarray and only non-numeric input (strings) falls through to the list form. The first-dimension check (== N / F) runs on both branches. Recorded as `MASTER_SPEC` Part 2 §3.10 Revision 1.3.

**Context.** `MASTER_SPEC` §3.10 originally typed both fields as `Array[(N/F, ...)]` (numeric), but the worked example §8.1 and the carry-through routing rule §6.1 both put XYZ per-frame **string** comments in `custom_per_frame["xyz:comment"]` — content the numeric-only type could not hold. The M1 golden fixture makes this executable, forcing the reconciliation now rather than at first extXYZ/XYZ parse.

**Rejected — keep the array-only type and route XYZ comments elsewhere** (e.g. `custom_global`). It would contradict §6.1's explicit "per-frame free text → `custom_per_frame`" routing and §8.1's worked object, and would lose the per-frame association (which comment belongs to which frame) that a length-F list preserves. **Rejected — a dedicated `custom_per_frame_text` field.** A parallel string-only surface doubles the carry-through routing table and the Capability-Matrix "arbitrary arrays" row for no gain; one first-dim-N/F surface that is agnostic to element type (numeric vs JSON scalar) is simpler and still shape-validated.

## D13 — POSCAR exporter writes **Cartesian** coordinates, not fractional (M3b)

**Decision.** The POSCAR/CONTCAR exporter emits coordinates in `Cartesian` mode with a scaling factor of `1.0` (the canonical `cell.lattice_vectors` are already absolute Å, Part 2 §3.4), even though the format natively supports `Direct` (fractional) too. Canonical positions are Cartesian by definition (Part 2 §4), so Cartesian output is written verbatim — no matrix inversion — which makes a parse→export→parse identity round-trip reproduce positions *exactly* (`np.array_equal`), not merely within tolerance.

**Rejected — write `Direct` (fractional) to mirror VASP's common convention.** Fractional output requires `frac = cart · lattice⁻¹`, and `cart · lattice⁻¹ · lattice` is only equal to `cart` up to floating-point rounding for a general (non-diagonal) lattice. That reintroduces representational error into the one place the strict-profile round-trip should be exact, and would force the identity test onto tolerance comparison rather than equality. VASP reads both modes, so nothing downstream is lost; the source's original mode is still recorded in `provenance.original_coordinate_system`. A future exporter option can offer `Direct` output once the tolerance model (Part 5 §4) governs that path.

## D14 — Identity round-trip equality is over **scientific content**, excluding `provenance` (M3a)

**Decision.** The identity round-trip criterion (`A → Canonical → A' → Canonical'`, Part 3 §3) compares the two objects' *scientific content* — `frames`, `trajectory`, `simulation`, `user_metadata` — for exact equality (deserialize-then-compare, D8), and deliberately **excludes `provenance`**. Golden-file comparison (parse vs hand-verified `expected.canonical.json`) compares everything *except* the volatile parse-event bookkeeping in `provenance.history` (wall-clock `timestamp`, `tool_version`, `parser_version`), which are normalised on both sides.

**Rejected — whole-object equality including `provenance`.** `provenance` records *how this particular file was read*: its `source_filename`, and the `original_coordinate_system` it happened to encode. A faithful re-export legitimately changes these — e.g. a POSCAR parsed from `Direct` source re-exports as `Cartesian` (D13), flipping `original_coordinate_system` from `"fractional"` to `"cartesian"` with zero information loss. Demanding provenance equality would make a correct round-trip fail on metadata that is *supposed* to reflect the differing inputs, and would force every parser to fabricate identical timestamps. Excluding provenance from the *equality* check does not weaken it: provenance is independently asserted by the golden tests, where its non-volatile fields must match exactly.

## D15 — One POSCAR implementation, registered twice as `poscar` and `contcar` (M3b)

**Decision.** POSCAR and CONTCAR are byte-identical formats (Part 3 §6.1), so a single `PoscarParser` / `PoscarExporter` class backs both, instantiated twice under two `format_id`s (`poscar`, `contcar`) that differ only in (a) the conventional filename each sniffs at confidence 1.0 and (b) a small sniff bias — POSCAR wins a nameless structural tie (`base_score` 0.6 vs 0.55), while a velocity/predictor-corrector tail tips the result to CONTCAR (`tail_bonus`), all surfaced as an `ambiguous` sniff rather than a forced winner (Part 3 §6.1). Factory helpers `make_poscar_parser()` / `make_contcar_parser()` (and the exporter pair) produce the two configured instances.

**Rejected — two independent parser/exporter classes.** Duplicates the entire POSCAR grammar (scaling factor, lattice, VASP-4 detection, selective dynamics, coordinate conversion, velocity tail) for two readings whose canonical output is identical by construction — the maintenance and drift cost the §6.1 "same canonical fields" guarantee exists to avoid. The one-class/two-registrations shape keeps the scientific logic single-sourced and localises the difference to sniff bias and the reported `source_format` label.

## D16 — Additive stable `ParseIssue` codes for the XYZ and POSCAR error contracts (M3a/M3b)

**Decision.** The two hand-rolled parsers emit stable machine `code`s beyond the single `XYZ_INCONSISTENT_ATOM_COUNT` the spec names explicitly (Part 3 §5 rule 4). XYZ: `XYZ_INCONSISTENT_ATOM_COUNT` (with `recovery_hint="truncate_at_last_valid_frame"`), `XYZ_EMPTY`, `XYZ_MALFORMED_HEADER`, `XYZ_INVALID_SYMBOL`, `XYZ_MALFORMED_COORDINATE`. POSCAR/CONTCAR: `POSCAR_MISSING_SPECIES` (with `recovery_hint="supply_species"`, the VASP-4 case of Part 3 §3 n.1), `POSCAR_INCONSISTENT_ATOM_COUNT`, `POSCAR_MALFORMED`, `POSCAR_INVALID_SYMBOL`, and the warning `POSCAR_PREDICTOR_CORRECTOR_CARRIED` (Part 3 §3 n.12). All obey the §5 contract: an error precludes a Canonical Object (raised as `ParseError`); a warning accompanies success (returned in `ParseResult.issues`); nothing is skipped silently (§5 rule 2). Recorded as `MASTER_SPEC` Revision 1.2 addendum item 12.

**Rejected — a single generic `PARSE_ERROR` code per format.** Collapsing distinct failures (missing species vs truncated file vs bad symbol) into one code destroys the machine-actionable distinction the error contract exists for — the Recovery Engine (Part 4 §3) branches on `recovery_hint`, and a `missing species` recoverable error must be distinguishable from an unrecoverable malformation. The spec's own worked example (§5 rule 4) establishes the granular, format-prefixed naming convention these codes follow.
