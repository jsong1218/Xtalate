# Xtalate — Developer Guide

This guide is for people building or extending Xtalate: setting up the environment, running the
lint/test gate, understanding how the pipeline fits together, adding a format, and following the
coding conventions that keep the converter trustworthy.

Read the [Architecture Overview](ARCHITECTURE.md) first for the mission, the principles P1–P6, and
the package layout — this guide assumes them. For the user-facing library and CLI surface, see the
[API Reference](API.md). For contribution mechanics (golden cases, PR expectations, licensing),
see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## 1. Dev environment

Xtalate is a pure-Python library + CLI; there are no services to run.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python ≥ 3.11. The only scientific dependency is ASE (extended XYZ and the ASE `.traj`
format); NumPy and pydantic power the canonical model, and PyYAML parses custom tolerance tables
and golden-corpus manifests.

## 2. The lint/test gate

CI runs exactly these checks, **in this order**, on Python 3.11 and 3.13. Run all of them locally
before you push:

```bash
ruff check .            # lint
ruff format --check .   # format — fails independently of `ruff check`; run both
mypy                    # types (strict)
lint-imports            # acyclic package layering (P2) — a required check
pytest                  # unit + golden + governance + property, with the coverage gate
```

`ruff format --check` fails independently of `ruff check`: a green `ruff check` does **not** mean
formatting is clean. If `ruff format --check` reports files, run `ruff format .` to fix them.

CI additionally installs the in-repo proof plugin before running the suite:

```bash
pip install --no-deps ./tests/fixtures/xtalate_toyfmt   # its 4 end-to-end tests skip when absent
```

A separate nightly workflow runs the full n×n round-trip matrix
(`XTALATE_FULL_MATRIX=1 pytest -m nightly`), the benchmark harness (`python -m benchmarks`), the
extended `hypothesis` profile, and `pip-audit`.

## 3. How the pipeline fits together

The single spine is `Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target
Format`, with four advisory subsystems (Discovery, Capability Matrix, Recovery, Validation). Each
subpackage under `src/xtalate/` owns exactly one of these responsibilities; the dependency
direction is downward-only (see [Architecture §7](ARCHITECTURE.md#7-package-layout-and-dependency-layering)).

The **`import-linter` layers contract** (configured in `pyproject.toml`, run as `lint-imports`) is
what enforces P2 mechanically: `schema` at the bottom, then `sdk`, then parsers/exporters/
capabilities, then the engines, then the CLI, with `registry` and `_time` also inside the
contract. A change that makes a parser import another parser, or a lower layer import a higher one,
fails the build. This is not a style rule — it is the physical guarantee that no format-to-format
shortcut can exist.

The **composition root** is `src/xtalate/registry.py`: `default_registry()` assembles the built-in
parsers/exporters and then discovers third-party plugins from entry points. Everything else
receives a `Registry` and reads formats through it — there is no global format table.

## 4. Testing strategy

All suites run under `pytest`. The layers:

- **Unit + laundering** (`tests/parsers/`, `tests/exporters/`) — per-format correctness, and proof
  that each parser returns `None` for anything the file does not actually say (the default-laundering
  obligation of P3).
- **Golden fidelity** (`tests/golden/`, `tests/schema/`) — curated real/synthetic source files with
  a hand-verified `expected.canonical.json`. Governed: every data file must be claimed by a
  `manifest.yaml` with a data license and source/expected hashes, and CI re-verifies the hashes and
  regenerates `tests/golden/ATTRIBUTIONS.md` (no manifest, no license, no merge).
- **Round-trips** (`tests/roundtrip/`) — identity round-trips plus cross-format two-hop
  (`A→B→Canonical′`) and three-hop (`A→B→A`), whose comparable subspace is computed from the
  Capability Matrix. This is the primary defense against silent parser/exporter asymmetry.
- **Report-completeness property** (`tests/property/`) — a `hypothesis`-driven test that every
  source field lands in `preserved`, `removed`, or `supplied`, and nothing is lost silently (the P1
  completeness invariant, also asserted at runtime in the Conversion Engine).
- **Streaming** (`tests/streaming/`) — proves the frame-chunked engine produces output and a report
  byte-identical to the materialized path ("chunking changes memory, never truth").

The suite enforces a **coverage ratchet** (`--cov-fail-under` in `pyproject.toml`): a floor set
below current coverage and raised as coverage rises, never lowered to green a PR. When iterating on
one test, `pytest tests/foo.py --no-cov` skips the coverage gate; run the full `pytest` before
pushing.

## 5. Adding a format

There are two ways to add a format. Implementing it **in-tree** puts it in `src/xtalate/parsers/`
and `src/xtalate/exporters/`; shipping it as a **separate installable plugin** requires no fork.
Both use the same SDK and the same rules.

### 5.1 Implement the parser/exporter

1. Subclass `ParserPlugin` / `ExporterPlugin` from `xtalate.sdk`. A parser reads one format into a
   Canonical Object and **never** reads another format or calls another parser (P2); an exporter
   writes one format from a Canonical Object and never reads native files.
2. Declare `capabilities()` **honestly**: a `PARTIAL` field with a note beats an optimistic `FULL`.
   The capability table has a sync test that will hold you to your declarations.
3. Keep the **default-laundering** suite green: prove your parser returns `None` for anything the
   source file does not actually state. Never default an absent field to a zero/identity value.
4. Add golden cases with licensed manifests, and pass the identity round-trip.

### 5.2 Ship it as an installable plugin (no fork)

A third-party distribution advertises its parser/exporter under Xtalate's entry-point groups;
`default_registry()` discovers them at startup through the *same* declaration validation and
duplicate-`format_id` guards a built-in format gets. In your package's `pyproject.toml`:

```toml
[project.entry-points."xtalate.parsers"]
myfmt = "my_package.parser:MyFormatParser"

[project.entry-points."xtalate.exporters"]
myfmt = "my_package.exporter:MyFormatExporter"
```

Each value resolves to your `ParserPlugin` / `ExporterPlugin` subclass — a class, or a
zero-argument factory returning one. **Import only the public SDK:** `xtalate.sdk` (the base
classes and the `FormatCapabilities` / `FieldCapability` declaration model) and `xtalate.schema`
(the Canonical Model). Never import `xtalate.parsers`, `xtalate.capabilities`, or any other
internal layer — a plugin that reaches past the SDK is coupled to internals that move without
notice. Discovery **fails loudly**: a broken installed plugin (import failure, malformed
declaration, `format_id` collision) is surfaced as an attributed error, never silently skipped.

A complete, installable worked example lives at
[`tests/fixtures/xtalate_toyfmt/`](../tests/fixtures/xtalate_toyfmt) — a minimal `toyfmt` parser +
exporter with its own `pyproject.toml` and entry-point declarations, importing only the public SDK,
which the test suite installs and drives end-to-end. Copy its shape.

> **Churn warning.** The Plugin SDK (`xtalate.sdk`) is **not frozen until v1.0**. An installable
> plugin — like an in-tree format — may need to follow SDK signature changes between minor
> versions. Pin the Xtalate version you build against, and watch the changelog for SDK changes.

## 6. Coding conventions (the non-negotiables)

These invariants are what make Xtalate trustworthy. A change that breaks one will not merge, however
convenient:

- **No defaulting, ever (P3).** A parser with no value for a field writes `None`. If an upstream
  library invents a default, launder it back to `None`.
- **The completeness invariant stays green (P1).** Every conversion accounts for every source field
  (`preserved` / `removed` / `supplied`); nothing is lost silently. Enforced at runtime *and* by the
  property test.
- **Recover explicitly, never guess (P4).** Missing-but-required data is supplied only through an
  explicit recovery choice, recorded as an Assumption — and no *unrequested* transformation even when
  it is standard practice (a Maxwell–Boltzmann velocity draw is emitted raw, with no
  centre-of-mass-drift removal).
- **Terminology is binding.** Field names, report names, and component names are fixed. If a name
  seems wrong, say so in your PR and propose the rename explicitly — never rename silently.
- **Docs and behavior change together.** A behavior change and its documentation change are one
  atomic PR.
- **No AI attribution in commits.** No `Co-Authored-By` AI trailer, no "Generated with…" line, and
  no AI listed as author or contributor in commit metadata, `CITATION.cff`, or release notes — the
  human maintainer is the author of record on every commit.
- **Never commit secrets.** No API keys, tokens, or credentials in code, config, fixtures, or commit
  messages — not even temporarily. Secrets are supplied via environment variables or an untracked
  local `.env` and referenced by name. (The current library + CLI has no network calls or
  credentials; this discipline is established ahead of the future Service layer.)

## 7. Where to go next

- [Architecture Overview](ARCHITECTURE.md) — the design and the principles.
- [API Reference](API.md) — the library and CLI surface.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — golden-corpus contributions, PR expectations, licensing.
