# Changelog

All notable changes to Xtalate are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The canonical schema version is
tracked separately from the package version and reaches `1.0.0` only in the v1.0 release
(`docs/MASTER_SPEC.md` Part 2 §5); v0.1 objects carry `schema_version = "0.1.0"`.

## [Unreleased]

The start of **v0.4**.

### Changed

- **Documentation: architectural-review changelog attributions corrected to match each release's
  tag and published artifact, and the versioning policy recorded (`docs/DECISIONS.md` D64).** Each
  version's post-release architectural review is folded into that version before tagging, not
  deferred to the next. The post-`0.2.0` review (D53–D55, golden-corpus governance hardening, the
  velocity-bearing corpus case, and internal de-duplication) now sits under **[0.2.0]** — the tag
  and PyPI artifact that actually contain it — and the post-`0.3.0` review (D62–D63, the XDATCAR
  Cartesian-scale fix, and the CLI plugin-error surfaces) under **[0.3.0]**. No code changes; the
  released `0.2.0` / `0.3.0` artifacts are unaffected. (v0.1 predates the policy — its review first
  shipped in the `0.2.0` artifact.)

## [0.3.0] — 2026-07-18

v0.3 — **"Trajectories at Scale."** Pipeline memory becomes **sub-linear in frames** through a
frame-chunked streaming core, and the two trajectory formats that need it land — **XDATCAR** and
the **ASE `.traj`** format — bringing the registered set to **six** of the seven Phase-1 formats
(CIF, the last, is v0.4). This release also opens the plugin surface — third-party
parsers/exporters are now discovered from Python entry points and proven against a real installed
distribution — and adds the performance-and-CI scaffolding a scaling release needs (a benchmark
corpus, a PR/nightly test-matrix split). It also folds in its own post-`0.3.0` architectural
review, per the versioning policy (`docs/DECISIONS.md` D64). Schema stays `0.1.0`; no normative
report/field shapes change.

### Added

- **Entry-point plugin discovery, proven against a real installed distribution (v0.3 M16;
  `docs/DECISIONS.md` D60–D61; `docs/MASTER_SPEC.md` Part 3 §7, Revision 1.16).** The §7.1
  mechanism, normative since Revision 1.2 but exercised only by first-party in-code registration
  through v0.2, is now implemented and end-to-end proven.
  - **Discovery in `default_registry()` (M16A, D60).** An additive third pass loads the
    `xtalate.parsers` / `xtalate.exporters` entry points (public
    `PARSER_ENTRY_POINT_GROUP` / `EXPORTER_ENTRY_POINT_GROUP` constants), each via `ep.load()()`
    (accepting a class *or* a zero-argument factory), and registers it through the **same**
    `register_parser` / `register_exporter` path — so third-party plugins get the declaration
    validation and duplicate-id guards for free. It **fails loudly**: a bad `capabilities()`
    declaration propagates `InvalidCapabilityDeclaration`; an import/construct failure or a
    wrong-kind object raises `PluginLoadError` naming the entry point; a `format_id` collision
    with a builtin is the registry's duplicate `ValueError` (builtins register first).
  - **An installable proof plugin (M16B, D61).** `tests/fixtures/xtalate_toyfmt/` is a real
    installable distribution (its own `pyproject.toml`, entry-point declarations, `py.typed`)
    implementing a trivial `toyfmt` parser + exporter through the **public SDK alone** (it imports
    nothing from `xtalate.parsers` or any internal layer). CI installs it before pytest; four
    detection-gated tests then prove `toyfmt` is discovered in `default_registry()`, queryable in
    the Capability Matrix, listed by `xtalate capabilities` (resolved from real dist-info in a
    fresh subprocess), and converts through the full pipeline (`toyfmt → xyz`, geometry preserved
    exactly). Installing it also enlarges the two-hop/round-trip matrices with `toyfmt` pairs — a
    discovered plugin proven across the whole spine, not just at registration.
  - **Contributor + spec surface (M16C).** `CONTRIBUTING.md` gains an entry-point packaging guide
    pointing at the worked example and carrying the R12 honesty clause (the SDK is not frozen
    until v1.0); the MASTER_SPEC §7.2 worked example's `import` lines are corrected to the real
    shipped modules (`xtalate.sdk` for the plugin bases *and* the `FormatCapabilities` /
    `FieldCapability` declaration model, `xtalate.schema` for the canonical types).
- **Benchmark corpus + PR/nightly test-matrix split (v0.3 M15).** The performance-and-CI
  scaffolding a scaling release needs.
  - **Benchmark harness** (`benchmarks/`): `python -m benchmarks` runs the Part 8 §4 performance
    benchmarks, each in its own subprocess for honest per-process peak RSS, **measured not gated**
    (it reports wall + RSS against a budget and exits non-zero only on a *crash*). Kept out of the
    coverage-gated pytest run.
  - **PR/nightly split** (Part 8 §2.4): a root `tests/conftest.py` registers `hypothesis`
    profiles (`pr`, default 200 examples / `nightly`, 2000) and **deselects `nightly`-marked
    items unless `XTALATE_FULL_MATRIX=1`** — no check is dropped, only deferred. The two-hop
    matrix parametrizes the full registry pair list but tags non-curated pairs `nightly`, so a new
    exporter auto-enrols in the nightly matrix (**P6**).
  - **Nightly workflow** (`.github/workflows/nightly.yml`): the full matrix, the benchmark run
    (artifacts uploaded), the extended property budget, and a non-blocking `pip-audit`
    dependency-vulnerability scan; a failure opens a tracking issue. `docs/MEMORY_CEILING.md` is
    finalized with the measured full-scale numbers.
- **ASE `.traj` format — the sixth registered format (v0.3 M14; `docs/DECISIONS.md` D58–D59).**
  Read and write for ASE's native binary trajectory. ASE `FixAtoms` constraints map to the
  canonical `Constraint(kind="fixed_atoms")`, and — honoring the absence convention — an empty
  ASE constraints list launders back to `None` rather than a present-but-empty list (D58). The
  wrapped ASE version is recorded in `provenance.parser_version` via an optional override on the
  shared `parse_record` / `build_provenance` helpers, so an ASE upgrade that changes behavior is
  attributable (D59). Two governed golden cases (a rich multi-frame relaxation anchor and a
  single-molecule laundering anchor), the identity round-trip, Capability-Matrix membership, and a
  sub-linear-in-frames streaming proof (`ase_traj → extxyz`) all land with it.
- **XDATCAR — a streaming-first trajectory format (v0.3 M13; `docs/DECISIONS.md` D57;
  `docs/MASTER_SPEC.md` Revision 1.15).** The fifth registered format and the one whose ordinary
  size (10⁴ configurations) forced chunking: a header-eager, configuration-lazy parser/exporter
  for both fixed-cell and per-frame-cell (NpT) forms (`trajectory.timestep = None`, since XDATCAR
  numbers configurations but declares no time axis). It also lands the two streaming-recovery
  halves M12 deferred: `truncate_corrupt_tail` ends a torn-write stream at the last good frame
  under an explicit `truncate` choice (recording the kept prefix as an Assumption and the dropped
  tail as an `XDATCAR_TRUNCATED` warning — never silent, never the default), and single-pass
  streaming `frame_selection` into a single-structure target (`convert_stream_select`, the
  XDATCAR→POSCAR case) produces a Conversion Report and output **byte-identical** to the
  materialized `convert`.
- **Frame-chunked (streaming) processing core (v0.3 M12; `docs/DECISIONS.md` D56,
  `docs/MEMORY_CEILING.md`).** An additive streaming surface on the plugin SDK —
  `ParserPlugin.parse_stream` / `ExporterPlugin.export_stream`, gated by `supports_streaming()`,
  with whole-file plugins adapted by a named materializing fallback (`sdk.streaming.stream_of` /
  `materialize`). A single-pass `PresenceAccumulator` reproduces `field_presence()` exactly over a
  stream; the extXYZ parser/exporter gain byte-identical streaming paths (the parser reads the file
  one frame block at a time); and `ConversionEngine.convert_stream` runs a recovery-free conversion
  with peak memory `∝ chunk size × atoms`, not frame count, producing the **identical Conversion
  Report** to the materialized `convert` (standing rule 3). Validation is chunk-aware too
  (`validation.streaming.validate_stream`): expected and re-parsed-output frames are diffed
  frame-pairwise over streams, so `convert_stream` is sub-linear end to end and its `ValidationReport`
  is byte-identical to the batch engine's. Mid-stream errors honor Part 3 §5: a `ParseError` at frame
  k propagates, the partial output is discarded, and no `ConversionResult` is returned — a half-written
  output never masquerades as a completed conversion. The milestone gate,
  `tests/streaming/test_streaming_memory.py`, proves the sub-linear-in-frames property against a
  committed deterministic generator. (The streaming `frame_selection`/`bounding_box` recovery
  interplay and the truncate-recovery half land with M13's XDATCAR, which exercises them; the seam is
  in place — see D56.)
- **`xtalate convert` now inherits the M12 sub-linear memory: eligible invocations route
  through the streaming engines (`docs/DECISIONS.md` D63; post-`0.3.0` architectural review).**
  With an `-o` file target in permissive mode and recovery presets empty (→ `convert_stream`) or
  exactly a `first`/`last`/`index` `frame_selection` (→ `convert_stream_select`), the CLI streams
  the conversion frame by frame — closing the v0.3 gap where the release's headline memory property
  was reachable only from the library API. Which path ran is not observable: output bytes and
  the Conversion Report are engine-guaranteed identical (M12 standing rule 3), pinned by CLI
  equality tests; the artifact is written via a temp file renamed on success, so a mid-stream
  parse error leaves a pre-existing `-o` file untouched. Everything else (strict mode, other
  recovery presets, non-streaming pairs, no `-o`) keeps the materialized path unchanged.
  Measured: 5 000-frame XDATCAR → extXYZ peaks at ~89 MB streamed vs ~354 MB materialized,
  byte-identical outputs.

### Changed

- **A broken installed plugin now surfaces on the CLI as a clean, attributed error (exit 1)
  instead of a raw traceback (post-`0.3.0` architectural review).** `default_registry()` runs for
  every command, so one plugin that fails to import, yields the wrong kind of object, collides on
  `format_id`, or carries a malformed declaration used to crash
  `inspect`/`convert`/`validate`/`capabilities` with an uncaught traceback. The CLI still refuses
  to run **any** command until the offending distribution is fixed or uninstalled — discovery
  never silently skips a broken plugin (Part 3 §7.1); only the failure's surface changed, not the
  fail-loud policy.
- **A discovered plugin's duplicate-`format_id` collision now raises `PluginLoadError` naming
  the offending entry point (`docs/DECISIONS.md` D62, partially revising D60).** Previously the
  registry's bare duplicate-guard `ValueError` propagated unwrapped, naming only the format —
  actionable for first-party code but not for an installed distribution. The original message is
  preserved verbatim inside the new one; `InvalidCapabilityDeclaration` still propagates unwrapped.

### Fixed

- **XDATCAR Cartesian-mode positions are now scaled by the scaling factor (§4; post-`0.3.0`
  architectural review).** The scale multiplier (including the negative-scale target-volume form)
  was folded into each frame's lattice but never applied to Cartesian coordinate rows, so a
  Cartesian XDATCAR with scale ≠ 1.0 parsed with positions off by the multiplier — while the
  emitted parse note claimed the scaling had happened (a P1 honesty violation). Direct-mode files
  were unaffected (fractional coordinates pick the scale up through the lattice product). Now
  matches the POSCAR parser's handling; covered by new Cartesian scale-2.0 and target-volume tests
  in `tests/parsers/test_xdatcar.py`.
- **The registry now enforces the id half of `InvalidCapabilityDeclaration`'s documented
  contract (`docs/DECISIONS.md` D62; post-`0.3.0` architectural review).** A plugin whose
  `capabilities()` declaration carries a different `format_id` than the plugin's own is rejected at
  registration (`InvalidCapabilityDeclaration` naming both ids) instead of silently producing a
  matrix keyed by one id whose stored declaration names another. All first-party plugins and
  `xtalate-toyfmt` already satisfied the check.

## [0.2.0] — 2026-07-15

v0.2 — **"trustworthy core complete."** The full Part 4 §3.3 recovery scenario catalog, the
POSCAR/CONTCAR velocity block with velocity/mass recovery, the cross-format round-trip matrix
with custom tolerance tables, the report-completeness property test, and the corpus-governance
and contributor surface that make outside golden-corpus contributions realistic. It also folds in
its own post-`0.2.0` architectural review (per the versioning policy, `docs/DECISIONS.md` D64):
report-semantics and JSON-tolerance correctness fixes, golden-corpus governance hardening, a
velocity-bearing corpus case, and internal de-duplication. Schema version is unchanged at `0.1.0`;
the four v0.1 formats (XYZ, extXYZ, POSCAR, CONTCAR) are the supported set. Pre-1.0, a minor bump
may still break — the plugin SDK is not frozen until v1.0 (risk R12).

### Added

- **Golden-corpus governance, contributor surface, and the v0.2 release (v0.2 M11).** The last
  milestone of the break: the governance that makes the golden corpus a corpus a stranger can
  extend without a maintainer in the loop, mechanized so it cannot silently rot.
  - **Manifest governance suite** (`tests/golden/test_corpus_governance.py`, `_governance.py`;
    `docs/MASTER_SPEC.md` Part 8 §3): every `manifest.yaml` is schema-validated (required
    fields incl. `origin.kind`, `origin.license`, `sha256`); a **missing or blank license is a
    hard CI failure** — *no manifest, no license, no merge* (§3.2). The recorded `sha256` of
    every source file is re-verified, so a silent fixture edit is impossible. CC-BY origins
    require an `attribution`, and published-dataset origins require a `source`.
  - **Schema-version sync check** (§3.3): every `expected.canonical.json` loads **through the
    migration chain** (`load_expected_through_migration_chain` — the identity today, the seam
    for real migrations when the schema versions past `0.1.0`), its embedded `schema_version`
    is cross-checked against the manifest's `canonical_schema_version`, and CI fails if any
    manifest lags more than one **major** version behind current.
  - **`tests/golden/ATTRIBUTIONS.md` regenerated from manifests and diffed in CI** (§3.2): the
    aggregate attribution file is *generated* (`python tests/golden/_governance.py`), never
    hand-edited, and the suite fails on any drift — an attribution obligation can never silently
    lapse.
  - **CI gates promoted** (Part 10 §1 deferral table, earliest v0.2): a **coverage ratchet**
    (`--cov-fail-under=91` in `pyproject.toml`, set below the measured ~92.6% branch coverage with slack — a floor
    that rises, never lowers, adding **`pytest-cov`** as a dev dependency), and the M0
    import-linter contract confirmed as a required check.
  - **`CONTRIBUTING.md`** (Part 10 §4.3): the docs-are-the-constitution rule, the non-negotiables
    (absence convention, completeness invariant, glossary), the add-a-format checklist, and the
    Tier 0 dev loop — plus the two honesty clauses (golden-corpus contributions are the invited
    path now; parser contributions are welcome-with-churn-warning until the SDK freezes at v1.0,
    risk R12).
  - **Issue + PR templates** (Part 10 §4.4–4.5, `.github/ISSUE_TEMPLATE/`,
    `.github/PULL_REQUEST_TEMPLATE.md`): the reports-are-the-bug-report intake for incorrect
    conversions and parse failures, a format-request template with a draft capability row, and a
    PR checklist including the **license-grant checkbox** for contributed files.
  - **Release:** version bumped to **0.2.0**; README "what v0.2 does / does not do" scope
    statement updated honestly (the round-trip matrix, custom tolerance tables, and recovery
    catalog now shipped). Tag + PyPI/GitHub publish remain the maintainer's manual step
    (`docs/DECISIONS.md` D52).
- **Report-completeness property test (v0.2 M10).** The single most important test in the repository
  (`docs/MASTER_SPEC.md` Part 8 §1.2), mechanically enforcing **P1** (no silent loss) and **P4** (no
  misfiled fabrication) over conversions that *have not happened yet* — the test-time generalization
  of the v0.1-M4 runtime completeness assertion.
  - **Two properties, re-derived in test code** (`tests/property/_properties.py`, deliberately not
    importing the production guard so it is an independent check — D50): **Property 1 — the
    completeness invariant** (every source-`present`/`mixed` path appears in `preserved` ∪ `removed`;
    every `supplied` entry names a source-`absent` path traced to a recorded Assumption) and
    **Property 2 — absence conformance** (every `removed` path is absent in the re-parsed output).
  - **Stage-1 generator — parametrized golden mutations** (`tests/property/_generators.py`):
    systematically nulls or populates **each optional canonical field-path** of the worked-example
    goldens (all eight schema categories reached) plus a per-frame `mixed` configuration, yielding 59
    valid Canonical Objects; `tests/property/test_report_completeness.py` drives every `(mutant,
    target)` pair through the real Conversion Engine under the `strict` profile with fixed recovery
    presets, asserting both properties on every report — including refused reports, which must still
    satisfy the completeness invariant. Every mutant re-validates through the model validators, so an
    invariant-violating mutation fails loudly at generation rather than producing a dead test.
  - **Stage-2 generator — hypothesis strategies over randomized objects** (`tests/property/
    _strategies.py`, `test_report_completeness_hypothesis.py`): randomized Canonical Objects with
    independent presence draws across all categories and **shrinking** on failure, exercising the
    field-*combinations* and multi-field `mixed` configs the one-at-a-time sweep cannot. Bounded to
    `max_examples=200` for the PR suite (Part 8 §5); v0.3's nightly workflow hosts the extended budget.
    Adds **`hypothesis`** as a **test-only** dev dependency (`docs/DECISIONS.md` D50) — the
    minimal-dependency posture governs runtime deps, which are unchanged.
  - **Independent-guard proof** (M10 done-means): feeding a tampered report — one `removed` entry
    dropped, or a `supplied` entry's Assumption removed — to the property checker is caught as silent
    loss / silent fabrication, demonstrating the property catches the class of bug the runtime
    assertion does, without the runtime assertion in the loop. A non-vacuity guard asserts the
    stage-1 lattice actually exercises both `removed` and `supplied` across its pairs.

- **Cross-format round-trip matrix suites + custom tolerance-table files (v0.2 M9).** v0.1 proved
  *identity* round-trips (`A → Canonical → A`); v0.2 adds the cross-format matrix that catches
  parser/exporter **asymmetry**, plus the deferred tolerance-file feature.
  - **Two-hop suite** (`A → Canonical → B → Canonical′`, `tests/roundtrip/test_two_hop.py`):
    parametrized over **every `(source, target)` pair enumerated from the registry**, driven through
    the real Conversion + Validation engines under the **`strict`** profile, with fabricative/
    selective gaps resolved by fixed recovery presets so Assumption recording is exercised end to end.
    The comparable subspace is **computed from the Capability Matrix at test time, never hand-listed**
    (`tests/roundtrip/_matrix.py`); reusing the Validation Engine's diff is deliberate (D49).
  - **Three-hop return** (`A → B → A`, `test_three_hop.py`): the symmetric-bug catcher over the
    curated high-risk pairs (`xyz↔extxyz`, `poscar↔extxyz`, `poscar↔contcar`), each anchored to its
    golden `expected.canonical.json` and diffed over the matrix-computed subspace by a dedicated
    comparator (`_compare.py`). Velocity round-trips (POSCAR↔extXYZ) join automatically via M8's
    capability rows — the matrix, not a hand-list, governs coverage.
  - **Registry-driven enumeration** (`test_matrix_enumeration.py`): registering a dummy in-test
    format grows the enumerated targets, sources, and pair list — and the comparable-subspace
    machinery answers for it — with zero suite edits, the mechanical guarantee behind **P6**.
  - **Custom tolerance-table files.** `--tolerance-profile FILE` now accepts a YAML/JSON table
    (`ToleranceProfile.from_mapping`) of per-quantity `{warn, fail}` overrides on the `default`
    bases; omitted quantities inherit their default. The non-configurable Part 5 §4.4 rules are
    enforced by rejection (the `k_*` multipliers and representational-bound floor are fixed; discrete
    checks admit no tolerance), with actionable errors. `xtalate convert … --tolerance-profile
    ./custom.yaml` and `xtalate validate --validation-report … --tolerance-profile ./custom.yaml`
    (offline re-threshold) both work; the profile name is embedded in the Validation Report.
  - **New dependency: PyYAML** (`[project].dependencies`) — the config language for tolerance tables
    and the golden-corpus manifests M11 governs (D48). See `docs/DECISIONS.md` D48–D49.

- **POSCAR velocity block + Maxwell–Boltzmann velocity/mass recovery (v0.2 M8).** The one deliberate
  v0.1 format deferral lands, together with the two velocity-family recovery scenarios it unlocks.
  - **POSCAR/CONTCAR Direct-mode velocities.** The velocity block is now read in both Cartesian
    (Å/fs, stored verbatim) and Direct (fractional) conventions; Direct velocities are converted to
    Cartesian Å/fs via the lattice, with a parse note, and an ambiguous mode line is read as Direct
    with a `POSCAR_AMBIGUOUS_VELOCITY_MODE` warning. Absence is preserved (`velocities = None`, never
    zero-filled). Export stays Cartesian (Direct-mode export is the M8 cut line).
  - **`missing_velocities`** resolves with `zero_init` (an explicit rest state), `maxwell_boltzmann`
    (`temperature_K`, `seed` — both recorded for reproducibility; the raw sample is emitted with no
    centre-of-mass-drift removal, `docs/DECISIONS.md` D43/D45), `upload_reference` (velocities
    borrowed from a second structure, shape-checked), and ✳`omit` (leave velocities absent — offered
    only when the target field is optional and the mode is permissive).
  - **`missing_masses`** resolves with `standard_masses` (IUPAC standard atomic weights from ASE, a
    *reported default* — D44) and `manual_input`. A `maxwell_boltzmann` draw over a source without
    masses **chains** a `missing_masses` recovery, resolving masses first and recording two
    Assumptions; for a target that cannot store masses (POSCAR) the masses are audited in `supplied`
    but not written (D47).
  - **Opt-in emission.** Velocity/mass fabrication is requested by supplying the recovery choice —
    it is never auto-triggered, since no v0.1 target *requires* these fields. The wiring lives in
    `ConversionEngine.convert` via a new `on_demand_fabricative_scenarios` helper (D46), which
    refuses incoherent requests (field already present on the source; or emission to a target that
    cannot store it) as caller errors.
  - CLI: `xtalate convert traj.extxyz --to poscar --recover missing_lattice=… --recover
    frame_selection=last --recover missing_velocities=maxwell_boltzmann,temperature_K=300,seed=42`
    produces a POSCAR with a velocity block, byte-identical on re-run. See `docs/DECISIONS.md`
    D43–D47.

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
- **A CONTCAR-with-velocities golden case** (`tests/golden/contcar/co-md-restart/`). CONTCAR was a
  round-trip *target* only; this synthetic case gives it a golden *source* with a Cartesian velocity
  block, so velocities now flow through the identity, two-hop, and three-hop round-trip matrices and
  the completeness invariant — previously the M8 velocity block was unit-tested but never exercised
  as system-level round-trip content.
- **Report-completeness property coverage for the fabricative recovery family**
  (`tests/property/test_fabricative_recovery_completeness.py`). `missing_velocities`
  (`zero_init`/`maxwell_boltzmann`) and the `maxwell_boltzmann → missing_masses` chain now flow
  through the **independently re-derived** M10 properties, not just the runtime completeness
  assertion — closing the gap where the opt-in fabricative path (never in the shared round-trip
  presets) reached only the runtime guard.

### Changed

- **A PARTIAL constraint capability now triggers recovery instead of auto-preserving.** A source
  carrying a non-empty `dynamics.constraints` list converted to a target that can represent only a
  *subset* of constraint kinds (POSCAR: `selective_dynamics`) no longer silently keeps-what-fits:
  *which* constraints survive changes the physics of a downstream relaxation, so it is now a recorded
  `constraint_representation` choice, and such a conversion **refuses without an explicit preset**.
  `NONE` capability stays ordinary bulk-reductive loss; `FULL` stays preserved; an empty
  `constraints=[]` preserves normally (`docs/DECISIONS.md` D36; `MASTER_SPEC` Revision 1.8).
- **Honest-loss annotations tightened.** An extXYZ `momenta` column now records the
  "velocities converted" parse-note even when it is explicitly all-zero (a source stating the atoms
  are at rest is information, §2 rule 3), and a CONTCAR velocity tail now annotates
  `source_units["velocities"] = "angstrom/fs"` with a parse-note, rather than storing the block
  with its unit left implicit.
- **Golden-corpus governance hardened (`docs/DECISIONS.md` D54).** Every data file under
  `tests/golden/` must now be claimed by a manifest — an unmanifested source/expectation, or the
  `manifest.yml` misspelling, fails CI rather than silently bypassing the license/hash/schema
  guarantees. Manifests gain a required `expected_sha256`, verified against `expected.canonical.json`
  exactly as `sha256` guards the source. The schema-lag bound is now two-sided (an expectation
  *ahead* of the current schema major is rejected as impossible, not just one too far behind). The
  two schema-serialization fixtures moved from `tests/golden/schema/` to `tests/schema/fixtures/`, so
  the `ATTRIBUTIONS.md` "every file is admitted only with a license" claim is now literally true.
- **Internal de-duplication (no behavior change).** The validation status-precedence and
  numeric-field→quantity tables are single-sourced in `xtalate.validation._shared`; the derived-path
  exclusion in `xtalate.schema.paths.DERIVED_PATHS`; the UTC-timestamp helper in `xtalate._time`.
  The single-frame reduction (re-index, `custom_per_frame` slice, `trajectory` drop) shared by
  `frame_selection` recovery and `split_all` export is now one `CanonicalObject.single_frame` method,
  so the two paths can never slice a reduced object differently. The M10 property harness deliberately
  keeps its own independent copies (D50).

### Fixed

- **A fabricated (`supplied`) field is no longer also listed `preserved` in the D51 flow
  (`docs/DECISIONS.md` D53).** When a `mixed` cell's only cell-bearing frame was dropped by
  `frame_selection` and `missing_lattice` fabricated a replacement, the report listed
  `cell.lattice_vectors`/`cell.pbc` in `preserved` **and** `removed` **and** `supplied` at once — the
  stale pre-flight optimistic-preserve prediction was never struck once recovery falsified it. The
  Conversion Engine now removes any `supplied` path from `preserved` (the two are mutually exclusive
  per path), leaving the honest **removed + supplied** pair D51 always documented.
  `absence_conformance` correspondingly exempts `supplied` paths from its must-be-absent check (a
  fabricated replacement is expected to reappear), applied identically in the runtime guard and,
  independently, in the M10 property re-derivation. Regression coverage in
  `tests/conversion/test_frame_reduction_completeness.py`.
- **JSON custom tolerance-table files with scientific-notation bounds now parse
  (`docs/DECISIONS.md` D55).** `--tolerance-profile ./table.json` routed through `yaml.safe_load`,
  whose YAML 1.1 float grammar reads dotless `1e-8` as the *string* `"1e-8"`, so a valid JSON table
  (exactly what `json.dumps` emits) failed with a confusing "must be a number". The CLI now parses
  `.json` files with `json.load` and other extensions with `yaml.safe_load`. Regression test in
  `tests/cli/test_cli.py`.
- **`frame_selection` no longer silently drops a per-frame field that lived only in a dropped
  frame (v0.2 M10).** Found by the stage-2 property test. When `frame_selection` reduced a trajectory
  to one structure, a per-frame path present *only* in the dropped frames (e.g. a `mixed`
  `dynamics.constraints`) was eliminated with no `removed` entry — silent loss (**P1**) that the
  runtime completeness invariant caught as a crash. `frame_selection` now records a `removed` entry
  for every per-frame path the reduction eliminates (`recovery.engine._per_frame_paths_lost`), and
  `conversion.engine` dedupes `removed` by path so a NONE-capability field flagged by both the
  capability diff and the reduction is listed once. Regression fixtures in
  `tests/conversion/test_frame_reduction_completeness.py`.
- **`constraint_representation=drop_all` now records the removal of an explicitly-unconstrained
  `constraints=[]` (v0.2 M10).** Also found by stage 2: an empty (present, §3.6) constraint list on
  the retained frame was nulled out of the write plan with a zero dropped-count and recorded in
  neither `preserved` nor `removed`. It is now reported `removed`.
- **A `mixed` cell converted to a lattice-requiring target no longer crashes the exporter (v0.2
  M10, D51).** A cell present in only some frames (`mixed`) whose cell-bearing frame `frame_selection`
  dropped left the POSCAR/CONTCAR exporter with no lattice and raised `ValueError`, because
  `missing_lattice` was detected only on a fully-`absent` required field. Pre-flight now offers
  `missing_lattice` on any *not-uniformly-present* required field, and the Recovery Engine resolves it
  **lazily** against the retained frame: fabricate a lattice for the cell-less frame (with a preset,
  never overwriting a real cell), refuse cleanly (without one), or no-op when the retained frame kept
  a real cell. The completeness invariant's P4 supplied-check is correspondingly relaxed to permit a
  path that is *both* `removed` (the dropped frame's cell) and `supplied` (the fabricated
  replacement) — honest, since both are reported. Regression fixtures in
  `tests/conversion/test_frame_reduction_completeness.py`; the M10 stage-2 generator now exercises
  `mixed` cells freely.
- **XYZ-with-comments → extXYZ no longer false-fails validation.** The extXYZ exporter writes a
  carried-through comment key (`xyz:comment`) faithfully, but the parser re-namespaced *every*
  comment key under `extxyz:`, so the value round-tripped under a changed path
  (`extxyz:xyz:comment`) and the Validation Engine's `metadata_preservation` check reported the
  planned path absent — marking every such conversion `failed`. The parser now skips the `extxyz:`
  tag for a key that already carries a `<format>:` namespace, so foreign keys round-trip verbatim
  while bare extXYZ keys are namespaced as before (`docs/DECISIONS.md` D41).
- **extXYZ → plain XYZ no longer false-fails on a foreign per-frame key (the D41 sibling).** Plain
  XYZ holds one free-text comment line per frame (`xyz:comment`) and nothing else, but its exporter
  declared the whole `custom_per_frame` container writable — so pre-flight predicted a foreign key
  (an extXYZ `config_type`) Preserved, the exporter silently dropped it, and `metadata_preservation`
  marked the conversion `failed`. `FormatCapabilities` gains `writable_custom_keys` (the per-key
  analogue of `representable_constraint_kinds`): an unwritable per-frame key is now honestly reported
  `removed`, while `xyz:comment` is still preserved (and the identity round-trip still passes) via a
  per-key write plan (`docs/DECISIONS.md` D42).
The remaining eight entries are a **post-v0.1 correctness pass** — defects found by a review that
exercised the shipped v0.1 code against real inputs, each reproduced, fixed, and pinned with a
regression test, folded into this release:

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

[Unreleased]: https://github.com/jsong1218/Xtalate/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/jsong1218/Xtalate/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jsong1218/Xtalate/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jsong1218/Xtalate/releases/tag/v0.1.0
