# ChemBridge — Engineering Decisions Log

> **Status:** Binding for implementation, subordinate to `MASTER_SPEC.md`. This log records the concrete build-time decisions that the spec leaves to implementation — the ones `docs/ARCHITECTURE_REVIEW.md` §3/§7 flagged as needed before code. Each follows the house style: state the decision, reject at least one alternative. New decisions append here with an ID; a decision that later contradicts the spec triggers a `MASTER_SPEC.md` Revision note in the same change (standing rule, `IMPLEMENTATION_PLAN.md` §4).

## D1 — One distribution, `src/` layout (resolves review §4.1, B4)

**Decision.** A single publishable distribution, `chembridge`, built from a `src/chembridge/` package with subpackages `schema`, `sdk`, `parsers`, `exporters`, `capabilities`, `discovery`, `conversion`, `recovery`, `validation`, `cli`. Not eight separately-versioned distributions.

**Rejected — one distribution per component** (`packages/canonical-schema/`, etc., each with its own `pyproject.toml`). Multiplies version numbers, editable-install wiring, and cross-package pinning for a solo maintainer with zero external consumers of a sub-component. The *logical* separation those directories exist for is delivered by the import-graph contract (D5), which works identically on subpackages. Splitting out (e.g. a slim `chembridge-sdk` at v1.0) stays available as an additive packaging change.

**Rejected — flat layout** (`chembridge/` at repo root, no `src/`). The `src/` layout prevents the classic "tests import the un-installed working copy instead of the installed package" footgun and makes the editable install the only import path.

**Naming refinement over `IMPLEMENTATION_PLAN.md` M0.** The plan's shorthand listed a combined `formats/`; this log instead keeps `parsers/` and `exporters/` as separate subpackages, because the spec gives them distinct components with distinct "Must NOT" contracts (Part 1 §2) and cites `packages/parsers`/`packages/exporters` throughout. Within each, modules are organized one-per-format (`parsers/xyz.py`, `exporters/xyz.py`). Recorded as `MASTER_SPEC` Revision 1.2 addendum item 8.

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
