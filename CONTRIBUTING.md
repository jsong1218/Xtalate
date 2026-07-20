# Contributing to Xtalate

Thank you for considering a contribution. Xtalate has one job — **loss-aware, fully
transparent file conversion** — and the contribution process is built to protect that job.
This guide is the practical companion to the [Architecture Overview](docs/ARCHITECTURE.md) and
[Developer Guide](docs/DEVELOPER_GUIDE.md); where they disagree, the design docs win.

> **What we're inviting right now (v0.3).** The **golden-corpus contribution** path is the
> invited, fully-supported way to contribute today: real-world sample files, with licenses,
> that harden the converter against formats we can't fake by hand. See
> [Contributing a golden case](#contributing-a-golden-case).
>
> **Parser/exporter contributions are welcome — with a churn warning.** The plugin SDK
> (`xtalate.sdk`) is **not frozen until v1.0** (roadmap risk R12). Until then, a format
> plugin you write may need to follow SDK signature changes between minor versions. We'll
> help, and we'll keep the churn visible in the changelog, but you should know it's there
> before you invest. If you want a format supported and don't want to track churn, filing a
> **Format request** issue with example files is itself a valuable contribution.

## Start here

1. **Read the design docs for your area.** The [Architecture Overview](docs/ARCHITECTURE.md)
   covers the mission and principles P1–P6; the [Developer Guide](docs/DEVELOPER_GUIDE.md) covers
   the pipeline, the testing strategy, and adding a format. **The docs are authoritative — code
   that contradicts them needs a docs PR first.** A behavior change and its documentation change
   are one atomic PR.
2. **Understand the *why* before changing behavior.** Most invariants below exist to prevent a
   specific class of silent loss; each names the principle it protects, so a change that seems to
   simplify one may be removing a guarantee on purpose.

## Ground rules (the non-negotiables)

These are the invariants that make Xtalate trustworthy. A PR that breaks one will not merge,
however convenient:

- **The absence convention (P3): no defaulting, ever.** A parser that has no value
  for a field writes `None` — never a zero velocity, an identity lattice, or an invented
  `energy = 0.0`. "Absent" and "present with value zero" are different states and the schema
  keeps them different. The **default-laundering** obligation is part of this:
  if an upstream library (e.g. ASE) invents a default, the parser must *unlaunder* it back to
  `None`.
- **The completeness invariant stays green (P1).** Every conversion accounts for every source
  field: it appears in `preserved`, `removed`, or `supplied`, and nothing is lost silently.
  This is enforced at runtime *and* by an independent property test (`tests/property/`). Any
  change to conversion behavior must keep both green.
- **Recover explicitly, never guess (P4).** Missing-but-required data is supplied only through
  an explicit recovery choice, recorded as an Assumption. No silent fabrication — and no
  *unrequested* transformation even when it's standard practice (a Maxwell–Boltzmann velocity
  draw is emitted raw, with no centre-of-mass-drift removal).
- **Reuse the binding glossary** ([Architecture §4](docs/ARCHITECTURE.md#4-glossary-binding-terms))**.**
  Field names, report names, and component names are fixed. If a name seems wrong, say so in your PR
  and propose the rename explicitly — never rename silently.

## Dev environment

Xtalate is a pure-Python library + CLI; there are no services to run.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the full gate locally before you push — CI runs exactly these, in this order, on Python
3.11 and 3.13:

```bash
ruff check .            # lint
ruff format --check .   # format (fails independently of `ruff check` — run both)
mypy                    # types (strict)
lint-imports            # acyclic package layering (P2) — a required check
pytest                  # unit + golden + governance + property, with the coverage gate
```

`ruff format --check` fails independently of `ruff check`; a green `ruff check` does **not**
mean formatting is clean. If it reports files, run `ruff format .`.

**Test layers** (all run under `pytest`): unit + laundering (`tests/parsers/`,
`tests/exporters/`), golden fidelity (`tests/golden/`, `tests/schema/`), round-trips
(`tests/roundtrip/`: identity + cross-format two-hop/three-hop), the report-completeness
property (`tests/property/`), and corpus governance (`tests/golden/test_corpus_governance.py`).
The suite enforces a **coverage ratchet** (`--cov-fail-under` in `pyproject.toml`) — it is a
floor set below current coverage, raised as coverage rises, never lowered to green a PR. When
iterating on a single test, `pytest tests/foo.py --no-cov` skips the coverage gate; run the
full `pytest` before pushing.

## Contributing a golden case

A golden case is a source file plus its hand-verified expected Canonical Object and a
`manifest.yaml`. This is the invited contribution path. The corpus governance suite
(`tests/golden/test_corpus_governance.py`) will hold you to every rule below.

1. **Pick a licensed file.** In preference order: (a) **synthetic**, hand-authored
   by you (license: Apache-2.0, the project's own); (b) **published open data** with an explicit
   redistribution-compatible license (CC0, CC-BY — attribution required); (c) **contributed**
   real-world files, with your explicit license grant recorded in the manifest and the PR
   template's license checkbox ticked. **A file without an explicit data license is not
   admissible, however convenient — "it's just a POSCAR" is not a license.**
2. **Lay it out** under `tests/golden/<format_id>/<case_name>/`: the source file, the
   `expected.canonical.json`, and a `manifest.yaml` (copy an existing one as a template). The
   manifest requires `case`, `format_id`, `source_file`, `expected_canonical`,
   `canonical_schema_version`, `sha256` (of the source file), `expected_sha256` (of the
   `expected.canonical.json`), and an `origin` block with `kind`, `license`, and — for published
   data — `source` (and `attribution` for CC-BY). Every data file under `tests/golden/` must be
   claimed by a manifest — an unmanifested file is a hard CI failure (no manifest, no merge).
3. **Compute the hashes:** `shasum -a 256 <source_file>` and `shasum -a 256
   expected.canonical.json` (or `python -c "import hashlib,sys;
   print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`), and put them in
   the manifest as `sha256` and `expected_sha256`. CI re-verifies both — a silent edit to either
   the fixture or its hand-verified expectation is impossible.
4. **Regenerate attributions:** `python tests/golden/_governance.py` rewrites
   `tests/golden/ATTRIBUTIONS.md` from the manifests. Commit the result; CI diffs it and fails
   if it's stale, so an attribution can never silently lapse.
5. **Run `pytest`** — the golden fidelity test and the governance suite must be green.

## Adding a format (parser/exporter)

The full checklist (see also [Developer Guide §5](docs/DEVELOPER_GUIDE.md#5-adding-a-format), and
the churn warning above):

1. Implement `ParserPlugin` / `ExporterPlugin` (`xtalate.sdk`). A parser reads one format to a
   Canonical Object and **never** reads files of another format or calls another parser (P2);
   an exporter writes one format from a Canonical Object and never reads native files.
2. Declare `capabilities()` **honestly**: a `PARTIAL` field with a note beats an optimistic
   `FULL`. The capability-table sync test will hold you to your declarations.
3. Add golden cases with licensed manifests (above), and pass the identity round-trip.
4. Keep the default-laundering suite green: prove your parser returns `None` for anything the
   file does not actually say.

## Packaging a format as an installable plugin

The section above covers *implementing* a parser/exporter. You can also ship one as a
**separate installable package** that Xtalate discovers automatically — no fork, no edit to
Xtalate's own code (see [Developer Guide §5.2](docs/DEVELOPER_GUIDE.md#52-ship-it-as-an-installable-plugin-no-fork);
**P6**). Your package declares its parser
and/or exporter under Xtalate's entry-point groups, and `default_registry()` loads them at
startup through the *same* declaration validation and duplicate-id guards a first-party format
gets. In your package's `pyproject.toml`:

```toml
[project.entry-points."xtalate.parsers"]
myfmt = "my_package.parser:MyFormatParser"

[project.entry-points."xtalate.exporters"]
myfmt = "my_package.exporter:MyFormatExporter"
```

Each value is an entry-point target resolving to your `ParserPlugin` / `ExporterPlugin`
subclass — a class, or a zero-argument factory returning one. **Import only the public SDK:**
`xtalate.sdk` (the `ParserPlugin` / `ExporterPlugin` base classes *and* the `FormatCapabilities`
/ `FieldCapability` capability-declaration model) and `xtalate.schema` (the Canonical Model).
Never import `xtalate.parsers`, `xtalate.capabilities`, or any other internal layer — a plugin
that reaches past the SDK is coupled to internals that move without notice. Once your package is
installed in the same environment, the format appears in `xtalate capabilities`, sniffing,
Discovery, conversion, and validation with zero changes to Xtalate.

A complete, installable worked example lives in this repository at
[`tests/fixtures/xtalate_toyfmt/`](tests/fixtures/xtalate_toyfmt) — a minimal `toyfmt`
parser + exporter with its own `pyproject.toml` and entry-point declarations, importing only the
public SDK, which the test suite installs and drives end-to-end (registry discovery, Capability
Matrix membership, the `xtalate capabilities` surface, and a full-pipeline conversion). Copy its
shape.

**The churn warning applies here too, doubly.** The plugin SDK (`xtalate.sdk`) is **not frozen
until v1.0** (risk R12): an installable plugin may need to follow SDK signature changes between
minor versions, exactly as an in-tree format does. Pin the Xtalate version you build against, and
watch the changelog for SDK changes.

## PR expectations

- **Small and single-purpose.** One concern per PR.
- **Name a rejected alternative** for every nontrivial design decision, in the PR description —
  it's the standard the whole document set holds itself to.
- **Fill in the PR template**, including the license-grant checkbox for any contributed files.
- **CI green**, including the golden, governance, and property suites.

## Conduct & licensing

Contributions are licensed under **Apache-2.0** (the repository license). Contributed test
files additionally require the license grant recorded in their manifest. By opening
a PR you affirm you have the right to contribute the code and files under these terms.
