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

> **Streaming is how the frame cap bounds memory.** A parser whose declared read `max_frames` is
> `None` (a trajectory-capable format) **must** implement `parse_stream` for the `max_frames` cap to
> bound peak memory. The cap's count pass (`enforce_max_frames`, M39-S3) streams frames one at a
> time through `parse_as_stream` and stops at `max_frames + 1`; a trajectory-capable parser that
> implements only the whole-file `parse` is materialized **before** the cap can fire, so an over-cap
> file is still refused correctly but peak memory is not bounded during the count. Single-structure
> formats (`max_frames=1`) are exempt — the cap skips them, so a whole-file `parse` costs them
> nothing they would not already pay. Every first-party trajectory format streams (extXYZ, plain
> XYZ, XDATCAR, ASE `.traj`); a third-party trajectory plugin must do the same to inherit the bound.

### 5.1.1 The parser-only variant (a code's output is a source, never a target)

Everything above assumes a format with a parser **and** an exporter. A DFT-*output* format is
different: `vasprun.xml` and `OUTCAR` are what VASP writes, so they are conversion **sources** that
can never be a **target** — nobody converts *into* a code's log. Such a format registers a
`ParserPlugin` with **no** paired `ExporterPlugin` (the D159 seam). That one omission does the rest:
the format holds a read capability row and **no** write row, so it is absent from every
conversion-target enumeration (targets derive from `exporters()`), shows read-only in
`xtalate capabilities`, and `convert --to vasprun` refuses with the ordinary unknown/unavailable
target error — never a new code. The in-tree precedents to copy are
[`src/xtalate/parsers/vasprun.py`](../src/xtalate/parsers/vasprun.py) and
[`outcar.py`](../src/xtalate/parsers/outcar.py): streaming-first readers over the shared `_vasp`
mapping core, each declaring its read capabilities honestly — including `NONE` for a field the
format genuinely cannot carry (vasprun's `electronic.magnetic_moments`, which only OUTCAR reads).

### 5.1.2 The required-parse-time-preset variant (a parse blocked on an interpretive choice)

Everything above assumes the file *declares* what it needs. A format can instead be genuinely
**ambiguous** on an axis the file itself does not state — and the rule is then **refused, never
defaulted** (P4/R3): the parse is blocked until the caller supplies the interpretive choice as a
`--recover` preset, and the choice is recorded as an Assumption on the parse, exactly like a
conversion-time recovery.

The in-tree precedent is LAMMPS' unit system: a dump declares its style in an `ITEM: UNITS` header
(modern LAMMPS writes it on the first snapshot), but a data file carries the unit system entirely out
of band — and LAMMPS itself does not name the unit style inside a bare `Atoms` block. The
`ambiguous_units` scenario (`src/xtalate/recovery/scenarios.py`, `HazardClass.FABRICATIVE` +
`INTERPRETIVE_SCENARIOS`) is offered with options `metal` · `real` · `si` **only when the file does not
say**: an undeclared-units file refuses with `RECOVERY_REQUIRED` until the caller passes e.g.
`--recover ambiguous_units=metal`, while a dump with a declared `ITEM: UNITS` header fires nothing.
The same shape repeats for `ambiguous_atom_style` (a data file's `Atoms # <style>` comment is honored
when present and refused when absent) and for the `missing_species` `species_map` preset when a dump
names atoms by numeric type only.

The machinery to copy lives in `src/xtalate/parsers/lammps_dump.py` (the `recovery_context` seam the
parser exposes for compound parse-time recovery) and `recovery/scenarios.py` (the scenario
registration + the option list). Three disciplines bind this variant:

1. **The option list grows by corpus evidence, not by the format's documentation.** The
   `metal`/`real`/`si` list is exactly what the M46–M49 goldens and the M49 wild corpus exercised;
   a style the corpus has not shown is **not** added from the LAMMPS manual (standing rule 3).
2. **A parse-blocking ambiguity is refused, never defaulted.** There is no "guess metal" fallback —
   an interpretive guess would silently misread every number in the file (P4).
3. **The preset is recorded, not silent.** The supplied choice lands in the parse's Assumptions and
   echoes into the Conversion Report like any recovery, so a downstream consumer can see that the
   file's units were supplied, not discovered.

See also the *Contributing real-world LAMMPS files* call (§5.6) — real files into the wild corpus
are how the evidence that grows these option lists is gathered.

### 5.1.3 The "structured input + log output" pairing variant (one calculation, two artifacts)

A code can present **two** artifacts of one calculation: an *input* that is a structured grammar
with declared per-card units (full read+write — a deterministic boundary mapping, never a
scenario), and an *output* that is a version-drifting log read **parser-only** through the
source-never-target seam (§5.1.1, D159). The two readers must **agree** on the shared initial
structure of the same run — a silent unit or sign disagreement between them is the cardinal bug at
MLIP scale (standing rule 4).

The in-tree precedent is the Quantum ESPRESSO pw.x pair (v1.4 M50–M52): `qe_pw_in` is the
structured input (the namelist + card grammar; every card declares `{angstrom|bohr|alat|crystal}`, so
conversion is a recorded boundary mapping and no unit ambiguity ever fires for a QE source), and
`qe_pw_out` is the log output (a version-drifting text log read parser-only, anchoring on stable
substrings and whitespace-splits so the QE 6.x ↔ 7.x layout drift parses to identical objects). The
shared mapping core `src/xtalate/parsers/_qe/` is where QE's structural conventions get pinned once
(`ibrav` expansion, per-card unit conversion, Bohr radius, species-label resolution) and both readers
consume it — the discovery happens once, never forked. The agreement is machine-checked by the
**input-echo cross-check** (`tests/parsers/_qe_run.py` + `test_qe_pw_out_crosscheck.py`, extended to
the wild corpus in M53): one run authored as both its input and its output, read by both parsers,
asserted equal on cell / species / positions within the strict tolerance profile.

Three disciplines bind this variant (mirroring the parser-only and required-preset variants):

1. **The two artifacts of one calculation must agree.** The input parser and the output parser are
two readers of one run; a disagreement — especially a stress-sign or position-unit one — is a
stop-the-line defect, not a style difference.
2. **The log parser refuses an unrecognized layout rather than partial-parsing it (P1).** QE
layouts beyond 6.x/7.x land in `QEOUT_UNRECOGNIZED_LAYOUT` with a corpus-contribution call — never a
silent partial read of a file the reader half-understands.
3. **Physics is never invented on export (P4).** A pw.x input written from a canonical object
carries exactly what the object had; run-required entries it lacks (cutoff, k-points, pseudopotential
files) are named in the honest-incompleteness warning, never defaulted.

The machinery to copy lives in `src/xtalate/parsers/_qe/`, `src/xtalate/parsers/qe_pw_in.py` +
`src/xtalate/exporters/qe_pw_in.py`, `src/xtalate/parsers/qe_pw_out.py`, and
`tests/parsers/_qe_run.py` (the agreement harness). Cross-reference (do not duplicate) the QE
real-world contribution call (§5.7) — a real input/output pair is exactly how the version-drift
axis gains evidence — and the CP2K handoff pointer (README), the first plugin expected to follow
this exact pairing pattern.

### 5.1.4 The multi-structure dataset-container variant (many independent structures in one file)

Some formats are **datasets**: one file holds many independent structures, possibly of different
composition (an ASE `.db` with many rows; DeePMD's grouped `.npy` next). The load-bearing rule is
that **a dataset is aggregation, not a new model** — the rows are *not* a trajectory, and folding them
into one Canonical Object's frames would break constant-N (Part 2 §3.2) and mislabel a dataset as one
structure. So a dataset format:

- **Parses one structure as one Canonical Object**, and **refuses** a multi-structure file on the
  single-file path with a *recoverable* issue that names the count (`ase_db` raises
  `ASEDB_MULTIPLE_ROWS` with `location="rows N"`). The refusal is resolved by a `frame_selection`-style
  scenario (`asedb_row_selection`: `index` picks one row, `all` is the batch fan-out) — which row you
  keep changes the science, so it is an explicit recorded choice, never guessed (P4). The batch layer
  detects exactly that refusal code and **fans the file out** into N per-row conversions; you write no
  batch code — implementing the refusal-with-count is the whole contract.
- **To be an `assemble` target** (combine N sources into one dataset file), declare
  `FormatCapabilities.assemble_capable=True` **and** override `ExporterPlugin.assemble(contributions,
  stream)`, together — the flag without the method (or vice versa) is a mistake. `assemble` is handed
  one `AssembleContribution` per source, in order, each carrying both the write-plan-filtered
  `canonical` object and the exact per-source `output` bytes; combine by whichever your container uses
  (extXYZ writes the `output` bytes verbatim for byte-identical concatenation; `ase_db` rebuilds one
  row per `canonical` and appends). The capability is **orthogonal to `max_frames`** — a
  single-structure target (`max_frames=1`, like `ase_db`) is still assemble-capable, and a
  trajectory target (`max_frames=None`, like XDATCAR) is *not* assemble-capable unless it opts in.
  Validation stays per contribution; the batch never validates the assembled whole.

**Aggregation, not curation (the boundary, restated for dataset formats).** A dataset format converts
and reports every structure it is given, completely — it does **not** select, split, dedup, or filter
rows by any criterion (roadmap §11; the manifest has no such field and rejects one). Which rows to
keep is the user's scientific judgment; Xtalate's job is to translate them all and report exactly what
each one kept and lost. See §6 for the batch surface these two seams (refuse-and-fan-out on input,
`assemble` on output) plug into.

### 5.1.5 The directory-format variant (a directory in, a directory out)

`deepmd_npy` (M56) is the first format whose native form is a **directory**, not a file: a DeePMD
system is a directory of NumPy arrays (`type.raw`, `type_map.raw`, `set.000/coord.npy`,
`set.000/box.npy`, plus the label arrays when present). Every seam the SDK had was single-file
shaped, so the directory case is its own additive variant, gated by a declared flag exactly like
`assemble` (D208) and streaming (D56):

- **Declare `FormatCapabilities.directory_format = True`** on both the read and write sides.
- **Read:** implement `ParserPlugin.parse_dir(files, *, dirname)` (an ordered relative-POSIX-path →
  bytes mapping) and `ParserPlugin.sniff_dir(entries, dirname) -> float`; `sniff` (the byte-head
  hook) stays `0.0` — a directory has no head, hints come from the listing. The generic sniffer
  scores a directory by delegating to each parser's `sniff_dir` with **no per-format logic** in
  discovery (Part 3 §6.1) — the same accept-threshold / ambiguity rules as byte-head sniffing.
  A parser's `parse_recover` receives its source as `parameters["directory_files"]` (never
  `stream`) — the recovery orchestrator's `_species_params` whitelist keeps the payload out of the
  recorded Assumption (pinned by test).
- **Write:** implement `ExporterPlugin.export_dir(canonical) -> Mapping[str, bytes]`; the engine
  carries the result on `ConversionResult.output_dir` (a *result* surface, never a Canonical
  Object field — schema stays untouched), and the CLI writes it under `-o DIR`. Validation
  re-parses the map **in memory** via `parse_dir` (no temp dir). A directory target is excluded
  from the streaming path.
- **Batch assemble:** declare `assemble_capable=True` **and** override
  `ExporterPlugin.assemble_dir(contributions) -> Mapping[str, bytes]` — the directory analogue of
  D208's `assemble`. The batch layer routes by the declared flags (no per-format knowledge, P2)
  and records the grouping as a dataset-level note: a count + the system names, never a digest
  (the wrapper gate).

The engine makes bytes and the CLI does the disk I/O — the same `split_all` separation, keyed by
path instead of index — so a directory input is just another source and a directory output is just
another target.

**The DeePMD dataset story, and the aggregation boundary restated with `set.*` sharding as the
worked example.** A DeePMD *system* is fixed-composition and fixed-order: one system ↔ one Canonical
Object (constant-N's natural ally, Part 2 §3.2), and a **trajectory** of frames is one system's
`set.000` (`max_frames=None`; Xtalate never splits frames across sets). DeePMD's `set.000`/`set.001`/
… sharding is a **train/test partition** — a scientific judgment, not a translation — so Xtalate
**writes one `set.000`** (never a split) and on read **concatenates every `set.*` in sorted order**
into one trajectory, reporting `DEEPMD_SET_PARTITION_DROPPED` (P1: the partition is information, so
its loss is announced, never silent). Many independent structures group **under `--batch`** by
composition into N systems (one `system_NNN/` per group) — never into one object. The virial is a
recorded deterministic mapping (`virial ↔ stress` via stress·volume, D211): read maps
`virial.npy → electronic.stress` directly, write maps `stress → virial.npy` **only when both stress
and a cell are present** (never fabricated, P3); no stress-carry scenario is involved because
DeePMD's convention is documented, not ambiguous.

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

### 5.4 Adding a recovery scenario

Formats are the plugin seam; **recovery scenarios are the core seam** — a scenario changes what the
engine *refuses* and *offers* for every format, so it lives in `src/xtalate/recovery/` and
`src/xtalate/conversion/preflight.py`, not in a separate distribution. The catalog is the Part 4
§3.3 table of `docs/MASTER_SPEC.md` made mechanical: `src/xtalate/recovery/scenarios.py` registers
every scenario the engine can see and hazard-classifies it, and the pre-flight diff emits an
unresolved scenario only when its trigger fires for the concrete source/target pair. The worked
example this section walks through is `ambiguous_stress_convention` — the first scenario added
after the v1.0 freeze (M40), and the first *interpretive* one. A scenario is five things; the
scenario's tests
([`tests/conversion/test_stress_convention_preflight.py`](../tests/conversion/test_stress_convention_preflight.py)
and [`tests/capabilities/test_stress_capability_rows.py`](../tests/capabilities/test_stress_capability_rows.py))
are the proof each one landed.

1. **Register it with a hazard class.** `SCENARIO_HAZARD` in `recovery/scenarios.py` maps the
   scenario code to exactly one of the three hazard classes (Part 4 §3.1). Bulk-reductive scenarios
   are never registered — they are reported `removed` and proceed in permissive mode — while
   selective-reductive and fabricative ones require an explicit choice. `ambiguous_stress_convention`
   registers `FABRICATIVE`: an explicit choice is required in both strict and permissive modes, never
   an auto-applied default. But it is also **interpretive** — it resolves the *meaning* of genuine
   source data (the sign convention of a carried stress tensor) rather than creating a value the
   source never had — so it records an `Assumption` with **no** `supplied` entry. That is a second,
   orthogonal marker: `INTERPRETIVE_SCENARIOS` (a frozenset) scopes the "fabricative ⇒ `supplied`"
   invariant to scenarios that genuinely invent a value. A scenario that interprets present data
   joins the marker; one that fabricates does not.
2. **Compute its option list.** `available_options()` in the same file returns the honest,
   *pair-specific* choice codes — computed, never static (Part 4 §3.3): a choice that is not
   scientifically coherent for the concrete pair, or not implemented in this version, is absent from
   the offered list rather than offered and then refused. `ambiguous_stress_convention` returns
   `["ase_sign_convention", "tension_positive"]`; `virial` is the named cut line — it needs the cell
   volume for the virial↔stress volume-scaling relation — so it is absent (naming it refuses) until
   v1.1.1. Do **not** document an option you have not built.
3. **Detect it in the pre-flight diff.** `conversion/preflight.py` emits an `UnresolvedScenario`
   (the descriptor lives in `recovery/scenarios.py`) carrying the canonical `path` a fabricative
   resolution would supply, a plain-language `detail`, and the option list computed at detection
   time — when the pair is known — so the engine validates against, and the refusal report echoes,
   exactly one list (P5). The `ambiguous_stress_convention` trigger is the *present-but-unmapped
   carry* shape: it fires only when the source carries
   `user_metadata.custom_per_frame["extxyz:stress"]` **and** the target declares a non-NONE write
   capability for `electronic.stress` — checked against the capability declaration, so the branch is
   correct the moment an exporter flips its row. Until then the carry is parked in the pre-flight's
   `pending` list (the optimistic-preserve convention), never classified against the container.
4. **Resolve it in the Recovery Engine.** `recovery/engine.py`'s `RecoveryEngine.resolve` applies
   the chosen option, validates it against the computed list, records an `AppliedAssumption` (and,
   for a genuinely fabricative scenario, a `SuppliedField`), and returns the amended object. The
   resolver also decides what the choice *writes*: resolving `ambiguous_stress_convention` retires
   the carry into `electronic.stress`, and a later export writes it back sign-reversed to the
   compression-positive convention its ASE-native files carry, reporting a
   `STRESS_SIGN_CONVENTION_CHANGED` warning.
5. **Give it a catalog row and a preset form.** The Part 4 §3.3 table in `docs/MASTER_SPEC.md` is
   the normative contract — trigger, options (✳ where pair-conditional), and the non-interactive
   behavior without a preset — and `ambiguous_stress_convention`'s row states `refused`: an
   undeclared convention is never interpreted, because a sign flip is invisible in the output. The
   CLI form is the same repeatable `--recover <scenario>=<choice>[,param=value...]` flag every preset
   takes:

   ```bash
   xtalate convert in.extxyz --to extxyz -o out.extxyz \
       --recover ambiguous_stress_convention=tension_positive
   ```

   Without the preset the conversion **refuses** — exit code 2, a first-class Conversion Report with
   `status="refused"`, `refusal.code="RECOVERY_REQUIRED"`, and `refusal.unresolved_scenarios`
   carrying exactly the options a retry may preset. Refusal is the default because it is the only
   default that neither fabricates data nor silently chooses which real data to discard (Part 4 §3.1).

**What a new scenario does *not* need, and the two honest deferrals.** No Web UI work: until the
v2.0 per-scenario copy batch, a new scenario renders in the wizard through the generic option list
and the shared loss vocabulary — functional and honest, with no frontend change
(`ambiguous_stress_convention` demonstrates exactly this state). No golden case is *required* — but
the M41 proof
([`tests/golden/extxyz/mlip-labeled-2frame/`](../tests/golden/extxyz/mlip-labeled-2frame), a governed
golden case with a licensed manifest) is the template to copy when a scenario is claim-defining: its
resolved round-trip deserves the same governed proof a format's identity round-trip gets. A
contributor adding a scenario should expect to touch `src/xtalate/recovery/` +
`conversion/preflight.py`, the scenario's tests, and the spec row — the whole point of this worked
example is that the seam is documented end to end, so the community can contribute scenarios the
way §5.1 lets them contribute formats (**P6** — extensibility over optimization).

### 5.5 Contributing real-world VASP files (a standing call)

The real-world corpus ([​`tests/wild/`](../tests/wild), governed by the same manifest/licensing
rules as `tests/golden/`) holds two kinds of file. The CIF cases under `tests/wild/cod/` are
genuine Crystallography Open Database entries vendored verbatim. The VASP cases under
`tests/wild/vasp/` are **authored-realistic fixtures** — self-licensed Apache-2.0 files modelled on
real VASP 5.x/6.x output, spanning single-point, relaxation, NpT MD, spin-polarized,
killed/truncated and layout-drift runs, with the OUTCAR↔vasprun **pair-agreement** as their oracle
(the CIF stoichiometry oracle does not apply, since VASP output declares no composition). The
harness is real and permanent; only batch 1's provenance is authored.

**Real-world OUTCAR / vasprun.xml pairs are welcome into the same harness.** Drop the files under
`tests/wild/vasp/<case>/` together with a `manifest.yaml` declaring the **exact**
`expectation.issue_codes` set the file must produce (plus `frame_count`, and a `pair:` naming the
sibling case of the other VASP format for the same run when both halves are contributed). Every
real-file anomaly must be triaged the way M20 requires: fixed in the parser, or named in the
manifest by someone who looked at it — the suite fails on any other outcome. The file's license
must permit redistribution (record it in `origin.license`; a `published-dataset` origin also needs
its source URL), and after adding a manifest, regenerate
`tests/golden/ATTRIBUTIONS.md` with `python tests/golden/_governance.py`. The current synthetic
OUTCAR↔vasprun pair cross-check is useful for mapping consistency but is not first-party proof of
VASP's stress convention; a **real paired run is explicitly ticketed for v1.4**. The maintainer
files that evidence ticket for batch 2; this documented call is the standing invitation.

### 5.6 Contributing real-world LAMMPS files (a standing call)

The LAMMPS cases under `tests/wild/lammps/` are **authored-realistic fixtures** — self-licensed
Apache-2.0 files generalizing the M46–M48 golden dumps/data files to real-world shapes: unit
styles (`metal`/`real`), orthogonal and triclinic boxes, typed and element-labeled atoms,
open-ended `compute`/`fix` output columns, a declared-`ITEM: UNITS` header, wrapped coordinates
with `ix iy iz` image flags, a molecular data file with carried topology, a genuine variable-N
deposition dump that refuses with measured per-frame counts, and an atom-style-comment-absent
data file. Their oracle is the **round-trip self-consistency** check (M49-S1): a file that
parses cleanly under its manifest's declared preset is re-exported through its own exporter and
re-parsed, and the two canonical objects must be scientifically equal — the parser and exporter
agreeing on meaning, the format-native ground truth for full read+write formats that declare no
composition and have no sibling reader.

**Real-world LAMMPS dump / data files are welcome into the same harness.** Drop the files under
`tests/wild/lammps/<case>/` together with a `manifest.yaml` declaring the **exact**
`expectation.issue_codes` set (plus `frame_count`), the `parse_recover` preset(s) the file needs
if it does not self-describe (CLI spelling, e.g. `ambiguous_units=metal` or
`missing_species=species_map,species=1:Si 2:O`), and the `roundtrip` declaration: `checked` for a
file whose re-export must agree with it, `skipped` with a stated reason for a file that
deliberately exercises a lossy export surface (the dump exporter does not write `ITEM: TIME`
carries) or that is refused. A refused file (`parse_error`) produces no object, so it declares
neither oracle. Every real-file anomaly must be triaged the way M20 requires — fixed in the
parser, or named in the manifest by someone who looked at it — and the unit/atom-style option
lists (`ambiguous_units` metal/real/si, `ambiguous_atom_style` atomic/charge/full) grow **only**
by this corpus evidence, never speculatively from LAMMPS's documentation.
The file's license must permit redistribution (record it in `origin.license`), and after adding a
manifest, regenerate `tests/golden/ATTRIBUTIONS.md` with `python tests/golden/_governance.py`.
The maintainer files the tracking issue for real batch files; this documented call is the
standing invitation.

### 5.7 Contributing real-world QE pw.x files (a standing call)

The QE cases under `tests/wild/qe/` are **authored-realistic fixtures** — self-licensed
Apache-2.0 files generalizing the M50–M52 QE goldens to real-world shapes, spanning QE 6.x and
7.x layouts across SCF / ionic `relax` / `vc-relax` (per-step cells) / MD runs, an unconverged
SCF (`QEOUT_UNCONVERGED` — the energy is still read and flagged, P3), a killed run torn
mid-write (refuses `QEOUT_TRUNCATED`; a companion case recovers under
`truncate_corrupt_tail=truncate`), decorated species labels (`Fe1` → Fe, `O_vac` → O, each
resolution recorded) plus the unresolvable-label refusal, two nonzero-`ibrav` inputs (2 fcc,
4 hexagonal), and a carried-payload input proving the K_POINTS / pseudopotential carry
survives the round-trip. Their oracles: the **round-trip self-consistency** check for
`qe_pw_in` (a full read+write format — parse, re-export through its own exporter, re-parse,
assert scientifically equal) and the **input-echo agreement** for an input/output pair (the
M50 input parser and the M52 output parser are the two readers of one run and must agree on
the shared initial structure — cell / species / positions — the `_qe_run` cross-check
assertion reused, standing rule 4). `qe_pw_out` is parser-only (D159), so it is never a
round-trip case.

**Real-world QE pw.x input/output files are welcome into the same harness.** Drop the files
under `tests/wild/qe/<case>/` together with a `manifest.yaml` declaring the **exact**
`expectation.issue_codes` set (plus `frame_count`), the `parse_recover` preset(s) the file
needs (`missing_species=species_map,species=Fe1:Fe O_vac:O` for an unresolvable label, or
`truncate_corrupt_tail=truncate` for a torn output), and the oracle declarations: `roundtrip:
checked` for a `qe_pw_in` whose re-export must agree with it, and `pair: <sibling case>`
naming the other half of the same run when you contribute the input *and* its output. A
refused file (`parse_error`) produces no object, so it declares neither oracle. Every
real-file anomaly must be triaged the way M20 requires — fixed in the parser, or named in the
manifest by someone who looked at it — and the supported `ibrav` set and recognized QE
layouts grow **only** by this corpus evidence, never speculatively from the QE docs. The file's
license must permit redistribution (record it in `origin.license`;
a `published-dataset` origin also needs its source URL), and after adding a manifest,
regenerate `tests/golden/ATTRIBUTIONS.md` with `python tests/golden/_governance.py`. The
maintainer files the tracking issue for real batch files; this documented call is the
standing invitation — batch 1 is authored-realistic, and real contributions are what make the
hybrid corpus honest.

### 5.8 The in-memory adapter seam (v1.5) — a library seam, deliberately *not* a format

Everything above §5.7 is the add-a-format path: registration, sniffing, capability rows,
round-trip enrolment, golden cases. The **in-memory adapters are none of that** — this subsection
sits beside the format path only so nobody goes hunting for it there.

`src/xtalate/adapters/` holds plain library functions between in-memory scientific-Python objects
and the Canonical Object — today, `from_pymatgen`/`to_pymatgen` for pymatgen's `Structure` and
`Molecule`. The boundary, stated plainly: **these serve library users composing Xtalate with
pymatgen in one process; they are not a registered format and never appear in the capability
matrix, the sniffer, or the CLI** — no `format_id`, no `builtin_parsers`/`builtin_exporters`
entry, no `docs/vocabulary.json` change, no round-trip-matrix row. pymatgen is an *optional*
extra (`xtalate[pymatgen]`) imported lazily inside the function bodies — `import xtalate` stays
pymatgen-free — and the subpackage sits in its own import-linter layer beside
`parsers`/`exporters` (it may import `sdk` + `schema`, nothing above).

The obligations they carry are the parsers', even without a report surface:

- **P3 laundering without a file.** pymatgen manufactures values on construction; audit each
  default and launder it to absence exactly as the ASE wraps do — a `Structure`'s fabricated
  total charge (0 / the oxidation-state sum when never set), a `Molecule`'s always-populated
  `_charge` (carry iff non-zero) and its manufactured `spin_multiplicity = nelectrons % 2 + 1`
  (carry iff it differs). Each audited distinction is pinned as a test in
  `tests/adapters/test_pymatgen_laundering.py` / `test_pymatgen_molecule.py`.
- **P1 by verbatim carry.** There is no ConversionReport to state a loss into, so anything with
  no canonical home carries verbatim under `user_metadata.custom_*['pymatgen:<key>']` (the
  extXYZ unmapped-column precedent) and restores on write. A value is mapped, laundered to
  absence, or carried — there is no fourth path. Notably `selective_dynamics` carries rather
  than becoming `fixed_atoms`: its per-axis booleans would silently flatten.
- **Periodicity is `cell` presence.** A `Structure` maps its lattice to `cell`; a `Molecule` is
  the `cell = None` case — never a fabricated identity lattice. `to_pymatgen` dispatches on the
  same fact, and a multi-frame trajectory refuses (`frame_selection` first) rather than silently
  exporting frame 0.
- **Provenance still stamps.** `source_filename = None` (constructed programmatically),
  `source_format = "pymatgen"` (an in-memory label — not a registered format id),
  `original_coordinate_system` from what the object natively holds, and a `parse` history entry
  folding the wrapped pymatgen version into `parser_version` (the D58/D59 discipline).

## 6. The batch surface

M54 gives the library and CLI a **batch** form: one manifest, many files, one aggregate record.

**The manifest** (`convert --batch manifest.yaml`) is a YAML mapping:

```yaml
sources:               # ordered: processing order AND report order; literal paths or globs
  - run1/vasprun.xml
  - run2/*.out
  - path: run3/POSCAR  # optional per-file override of the shared settings
    override:
      acknowledge_loss: true
target: extxyz
output_mode: per-file  # per-file | assemble (combine N sources -> one dataset container)
mode: permissive       # permissive | strict
recovery_choices:      # the same --recover preset grammar, one string per preset
  - frame_selection=last
  - missing_lattice=bounding_box,padding_ang=5.0
tolerance_profile: default
acknowledge_loss: false
acknowledge_parse_warnings: false
```

Globs resolve deterministically (sorted) and the concrete file list is recorded in the report —
manifest order is processing order and report order. The shared conversion settings live in the
manifest; in batch mode the CLI refuses `--mode`/`--recover`/`--tolerance-profile`/the
acknowledge flags rather than silently ignoring them (the manifest wins by design).

**The two output modes.** `per-file` writes one file per source into the `-o` directory
(`<stem>.<target>`; POSCAR/CONTCAR take no extension). `assemble` combines all sources into
**one** dataset container (`-o out.extxyz`, `-o out.db`). The combine is **exporter-mediated** and
gated on a **declared** capability, not a hardcoded target list (M55-S4, D208): a format opts in by
setting `FormatCapabilities.assemble_capable=True` and overriding `ExporterPlugin.assemble(...)` — the
batch layer holds no per-format knowledge of how a container is built (P2). extXYZ (assemble-capable)
concatenates the per-source output bytes verbatim, so the assembled file is byte-identical to joining
the individual conversions; ASE `.db` (assemble-capable) appends one row per source into one database.
A target that does not declare the capability (POSCAR, XDATCAR, …) refuses `assemble` with a clear
message; there is never a silent fallback to per-file. Validation stays **per contribution** (each
source converts and validates on its ordinary path — the assembled whole is never the validation
unit), and a mixed-composition assemble surfaces an honest dataset-level note (extXYZ's
`EXTXYZ_VARIABLE_ATOM_COUNT`), never a per-file loss.

**Directory assemble (M56-S3, D214).** A directory-format target (``deepmd_npy``) assembles through
the directory analogue of the same seam: it declares ``assemble_capable`` **and** overrides
``ExporterPlugin.assemble_dir(contributions)``, and the batch layer routes by the declared
``directory_format`` + ``assemble_capable`` flags — still no per-format knowledge in the batch (P2).
The output is a **directory of systems** under ``-o DIR`` (``system_000/``, ``system_001/``, …): a
DeePMD system is fixed-composition, so contributions group **by composition** into one system per
group (deterministic, by first appearance; frames of one composition join that system's ``set.000``).
The grouping is a **declared property of the target layout**, recorded in the aggregate note as a
count + the system names (the wrapper gate — never a digest of per-file content), and a
single-composition batch produces exactly one system. Sources whose atoms are ordered differently are
separate systems — Xtalate never silently reorders atoms to force a merge (identity
``atom_permutation``).

**Multi-structure container inputs fan out.** A source that holds many independent structures — a
multi-row ASE `.db`, which refuses `ASEDB_MULTIPLE_ROWS` on the single-file path because a dataset is
aggregation, not one Canonical Object — **fans out** under `--batch` into N ordinary per-row
conversions in the one `BatchReport` (each an explicit, recorded `asedb_row_selection=index` choice
keyed `<path>::row=<i>`, each embedded report byte-identical to converting that row alone). So the two
dataset containers are symmetric: assemble N sources **into** a `.db`, and fan a multi-row `.db` back
**out** — `extxyz ↔ ase_db` translation runs both directions. This is the seam every future
multi-structure format (DeePMD next) rides; declaring `assemble_capable` is all a new dataset target
needs to join it.

**Per-file honesty (the aggregate embeds, never summarizes).** The `BatchReport` carries
dataset-level **tallies** (converted / refused / failed, plus label-presence counts) and embeds
each file's `ConversionReport`/`ValidationReport` **verbatim** — the same file converted alone
and inside a batch serializes byte-identically, so the aggregate cannot elide a per-file loss.
One file's parse failure or refusal is that file's outcome and the batch always completes;
`--fail-fast` stops at the first non-converted file for the caller who wants that. A refusal is
a completed conversion, exactly as on the single-file path.

**Aggregation, not curation (roadmap §11, quoted).** The manifest has **no** fields for frame
selection by criteria, train/test splitting, or deduplication — a manifest carrying such a key
is rejected, and there are no `--select`/`--split`/`--dedup` flags. Roadmap §11's second
corollary is the boundary's statement: *"Not a dataset curator. Splitting, deduplicating-by-
similarity, rebalancing, and outlier filtering are scientific judgments about data, not
translations of it. Batch operations (v1.5) convert what they are given, completely and
reported."* Xtalate converts what you point it at and reports exactly what each file contributed
and lost — the curation is yours, and the record is complete enough to audit it.

**The batch exit code** is the worst per-file outcome under the existing 0–5 vocabulary: a batch
with one refusal exits 2, one with a parse error exits 4, an all-clean batch exits 0; a
malformed manifest (or a manifest carrying a scope-refused key) is a usage error, exit 1.

**The HTTP form is the same contract, an additive job kind (M58-S1, D217).** `POST
/v1/batch/convert` reproduces `run_batch` on the wire — the API adds **no batch logic** beyond
the transport. Where the CLI manifest names file paths, the request names uploaded `file_id`s;
where `run_batch` converts in-process, the endpoint **fans out to ordinary child convert jobs**
(a nullable self-FK `jobs.parent_job_id`, Alembic 0004), each a navigable record with its own
pause, refusal, and expiry — the same `execute_job` machinery a lone `convert` job rides, never a
second engine. The parent's `result` is the same aggregate shape (reused
`BatchTallies`/`LabelPresence` + one verbatim-embedding entry per child), rebuilt from the
persisted child rows on every poll, and the envelope carries an additive `children` projection
so the record is navigable in every state. Per-file consent stays per-file: a paused child
leaves the parent honestly non-terminal with **no** batch-level recovery block, and the parent
re-drives itself lazily on poll once every child is terminal. The new error codes
(`EMPTY_BATCH`, `JOB_CANCELLED`) go through the D104 registry; nothing in `schema/` moves
(SCHEMA_VERSION stays `1.0.0`). Adding a job kind like this is the Part 6 §7 additive path: a
new `JOB_KINDS` member, a router arm, and a runner branch — never a change to the frozen single-
file contract.

## 7. Coding conventions (the non-negotiables)

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

## 7.5 The viewer: a read-only consumer seam (v1.6 M59–M63)

The Web UI's Structure/Compare viewer is the first realized consumer of the §3.2 secondary goals: it
**reads** the M59 geometry endpoints (`GET /v1/files/{file_id}/geometry`, `GET
/v1/conversions/{conversion_id}/geometry?side=source|output`) and the reports, renders the Canonical
Object the engine already parsed, and never re-derives a fact (no client unit math, no recomputed
diffs, no hidden export — §3.2). It is read-only by contract: measurement, selection, and rendering
export are documented omissions, and analysis overlays are v1.8's seam. Bonds are a **display
heuristic** (D234): off by default, the enabled view carries the persistent badge, and no report
mentions them. The a11y posture (D241): the reports are the accessible record; the viewer is an
additional presentation — viewer chrome, not the canvas, meets the WCAG AA bar.

## 8. Where to go next

- [Architecture Overview](ARCHITECTURE.md) — the design and the principles.
- [API Reference](API.md) — the library and CLI surface.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — golden-corpus contributions, PR expectations, licensing.
