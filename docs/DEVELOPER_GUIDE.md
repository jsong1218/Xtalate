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

CI additionally installs two out-of-tree plugins before running the suite. The `toyfmt` fixture is
the minimal discovery proof — installed `--no-deps`, its tests **skip when absent**:

```bash
pip install --no-deps ./tests/fixtures/xtalate_toyfmt   # its 4 end-to-end tests skip when absent
```

The reference plugin is the **compatibility canary** — installed **before** `lint-imports` (so its
`forbidden` import contract is evaluated) with its suite a *required* part of the run, so a core
change that breaks the frozen public SDK fails CI (see [§5.3](#53-the-compatibility-canary)):

```bash
pip install --no-deps ./plugins/example-format         # its suite is required, never skipped
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

The complete, published worked example this section points at is the reference plugin
[`plugins/example-format/`](../plugins/example-format) — a small, deliberately simple format
(`exfmt`) that exists to be *copied*: a parser, an exporter, honest capability declarations, golden
cases with licensed manifests, and its own end-to-end test suite, built **only** against the frozen
public SDK. It is a separate installable distribution, and CI treats it as a compatibility canary —
a core change that breaks it fails the build (see [§5.3](#53-the-compatibility-canary)). Every step
below names the file in it that demonstrates the step.

Most formats are a single module per side. CIF is the exception and the precedent for a large one:
its reader is a *package*, `src/xtalate/parsers/cif/`, split into four stages with a one-way flow —
tokens, then a format-shaped document, then format-level invariants, then the Canonical Object —
where the first three know nothing of `xtalate.schema`. If a format you are adding is big enough
that its syntax and its semantics want separating, follow that shape; the split is worth its cost
when the backend might later be replaced by a library, and not otherwise.

### 5.1 Implement the parser/exporter

1. Subclass `ParserPlugin` / `ExporterPlugin` from `xtalate.sdk`. A parser reads one format into a
   Canonical Object and **never** reads another format or calls another parser (P2); an exporter
   writes one format from a Canonical Object and never reads native files. In the reference plugin
   these are `ExampleFormatParser`
   ([`parser.py`](../plugins/example-format/src/xtalate_examplefmt/parser.py)) and
   `ExampleFormatExporter`
   ([`exporter.py`](../plugins/example-format/src/xtalate_examplefmt/exporter.py)) — each a single
   module importing only `xtalate.sdk` and `xtalate.schema`.
2. Declare `capabilities()` **honestly**: a `PARTIAL` (or `NONE`) field with a note beats an
   optimistic `FULL`. An over-declaration is not a cosmetic slip — the pre-flight predicts the field
   preserved, so the Conversion Report promises the user something the artifact does not carry. This
   is the lesson the reference plugin was built to teach concretely. `exfmt` reads an optional
   per-frame label into `user_metadata.custom_per_frame['exfmt:label']`, but its exporter **cannot
   write it back**, so `ExampleFormatExporter.capabilities()` declares that container `NONE` with a
   note — and a file carrying a label reports that key `removed` in pre-flight, before any bytes are
   written, instead of promising it and dropping it. **`NONE` and `PARTIAL` are the two honest shapes
   of "less than FULL":** declare `NONE` when the format writes *nothing* in a container (as `exfmt`
   does), and `PARTIAL` when it writes *some* of it —
   - For a carry-through container you write only *some* keys of, name them in
     `writable_custom_keys`. If the writable set is genuinely open-ended but its *spelling* is
     constrained, declare a `writable_custom_key_pattern` instead — a `{container_path: regex}`
     map applied in the same place, so a present key whose name does not `fullmatch` is reported
     `removed` before any bytes are written. extXYZ declares `^extxyz:[^:]*$` because its
     `Properties=` grammar separates fields with `:`, so a key like `cif:occupancy` cannot be
     spelled at all. Declare a list or a pattern for a container, never both. (Plain XYZ is the
     `PARTIAL` counterpoint to `exfmt`'s `NONE`: it *can* write exactly one key — its `xyz:comment`
     line — so it declares the container `PARTIAL`, not `NONE`.)
3. Keep the **default-laundering** suite green: prove your parser returns `None` for anything the
   source file does not actually state. Never default an absent field to a zero/identity value.
   `exfmt`'s parser sets every field the source does not carry — cell, dynamics, electronic, all of
   it — to `None`, and its test suite asserts exactly that.
4. Add golden cases with licensed manifests, and pass the identity round-trip. The reference plugin
   carries two, both under [`plugins/example-format/tests/golden/exfmt/`](../plugins/example-format/tests/golden/exfmt):
   `water-monomer` (no label — the clean identity round-trip) and `labeled-methane` (with a label —
   the case that exercises the `removed` story end to end). Each has a `manifest.yaml` mirroring the
   `tests/golden/` schema (`case`, `format_id`, `source_file`, `expected_canonical`,
   `canonical_schema_version`, `sha256`/`expected_sha256`, and an `origin` block with `kind` and a
   data `license`). The identity round-trip (`A → Canonical → A`, diffed within tolerance) is
   deliberately lossy by exactly the label and nothing else — the comparable subspace comes from the
   Capability Matrix, so a drop the plugin did *not* declare would fail it.
5. Add the format's row. **In-tree**, a format appears in the capability table the sync test guards;
   a row you forget, or a declaration your row disagrees with, fails that test. **As a plugin**,
   there is no hand-authored row to add at all: once installed, the format appears in
   `xtalate capabilities`, `GET /v1/capabilities`, the `/formats` explorer, sniffing, Discovery,
   conversion, and validation with **zero changes to Xtalate** — the P6 payoff, and the reason
   `exfmt` shows up in the nightly round-trip matrix (as both source and target) without a core edit.

### 5.2 Ship it as an installable plugin (no fork)

A third-party distribution advertises its parser/exporter under Xtalate's entry-point groups;
`default_registry()` discovers them at startup through the *same* declaration validation and
duplicate-`format_id` guards a built-in format gets. In your package's `pyproject.toml` (the
reference plugin's own [`pyproject.toml`](../plugins/example-format/pyproject.toml) is the template):

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
notice, and the `import-linter` `forbidden` contract that guards the reference plugin proves that
wall mechanically. Discovery **fails loudly**: a broken installed plugin (import failure, malformed
declaration, `format_id` collision) is surfaced as an attributed error, never silently skipped.

**The reference to copy is [`plugins/example-format/`](../plugins/example-format)** — the complete,
installable `exfmt` plugin described above. There is a second, deliberately smaller installable
example, [`tests/fixtures/xtalate_toyfmt/`](../tests/fixtures/xtalate_toyfmt): it is the minimal
*discovery* proof — the smallest thing that shows entry-point discovery working against a real
installed distribution — installed `--no-deps` with tests that skip when it is absent, all-`FULL`
and outside the matrix and the golden corpus. Reach for `toyfmt` when you want the bare mechanism;
copy `plugins/example-format/` when you are building a real format, because it is the one that also
shows the honest-loss declaration, the golden cases, and the CI canary.

### 5.3 The compatibility canary

The reference plugin is not only documentation — it is a **hard CI gate**. On every PR, CI installs
`plugins/example-format` and runs its test suite as a *required* part of the run (not skip-if-absent
like `toyfmt`); the install happens **before** `lint-imports`, so the plugin's `forbidden` import
contract is evaluated too. A core change that breaks the plugin — a renamed or re-typed public SDK
symbol, a changed signature, a broken parse/export/capabilities path — fails the build. The two
gates are complementary: `lint-imports` catches a *structural* break (the plugin reaching past the
public wall), and the pytest canary catches an *attribute/signature-level* break of the frozen
surface (the import graph can be unchanged while a renamed symbol still breaks every importer).
Together they are what gives the frozen-SDK stability promise below mechanical teeth.

> **Stability promise.** The Plugin SDK (`xtalate.sdk`) is the **frozen 1.x contract** as of the
> v1.0 contract freeze. The ABCs an installable plugin builds against — `ParserPlugin`,
> `ExporterPlugin`, the streaming surface, `ParseResult`/`ParseIssue`/`ParseError`, and
> `FormatCapabilities` — evolve **additively only** within 1.x: new optional hooks and capability
> fields arrive with safe defaults, and no existing signature, field meaning, or the absence/error
> contract changes. A plugin built against 1.0 keeps working across every 1.x release. The freeze
> covers the public SDK only — the `_`-prefixed internal surface is not part of the contract — and a
> breaking change waits for 2.0, with migration notes.

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
- **Every release states its schema version.** The `CHANGELOG.md` release entry — and the
  `[Unreleased]` section that accrues the next release — carries a required `Schema version:` line
  naming the canonical `schema_version` it ships, guarded against `xtalate.schema.SCHEMA_VERSION` by
  `tests/test_changelog_schema_version.py`. The product version and the schema version move under
  distinct rules (see [Versioning and stability](../README.md#versioning-and-stability)).
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
