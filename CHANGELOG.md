# Changelog

All notable changes to Xtalate are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The canonical schema version is
tracked separately from the package version and reaches `1.0.0` only in the v1.0 release
(`docs/private/MASTER_SPEC.md` Part 2 §5); v0.1 objects carry `schema_version = "0.1.0"`.

## [Unreleased]

## [0.5.0] — 2026-07-23

v0.5 — **"Service."** The whole engine, unchanged, now speaks HTTP. A FastAPI application exposes
`inspect` / `convert` / `validate` under `/v1` as async jobs (submit → poll `GET /v1/jobs/{id}` →
retrieve), backed by a persistence layer (PostgreSQL + S3-compatible object storage in Tier 1;
SQLite + filesystem in Tier 0) and an RQ worker. The API contains **no scientific logic** — an
import-linter contract enforces the direction — and every response embeds the pydantic report models
**verbatim**, no parallel DTOs. The two rules the product turns on are named tests a future refactor
cannot delete quietly: a **refused conversion is a completed HTTP-200 job**, never a 4xx; and an
interactive recovery pause **expires to a refusal, never a silently-applied default**. The library
and CLI are byte-for-byte unchanged.

### Added

- **Backend skeleton + persistence adapters (M21).** The FastAPI app factory, the request-id
  middleware, the single error-envelope path (`{error: {code, message, details, request_id,
  documentation_url}}`), and the backend-agnostic repository over four tables (uploads, jobs,
  conversions, reports). Two interchangeable backends per interface — SQLite/filesystem (Tier 0) and
  PostgreSQL/MinIO (Tier 1) — chosen by configuration alone and proven by an adapter parity suite.
- **Async job model + state machine (M22).** The full lifecycle `queued → running →
  completed | failed | cancelled`, with a transition-table module tested over every legal and
  illegal edge; idempotent `inspect`; and a crashed worker mid-job resolving to `failed` with a
  structured envelope, never a stuck `running` row.
- **Interactive recovery + cancellation (M23).** `allow_recovery` pauses a convert to
  `awaiting_recovery` carrying the pre-flight draft report and the **computed** option lists;
  `POST /v1/jobs/{id}/recovery` validates each choice against exactly the offered options and
  resumes (a partial resume pauses again); an unattended pause **expires to a refused conversion**.
  Cancellation is legal from every non-terminal state and writes no report.
- **Files, downloads, lifecycle, limits (M24).** Bounded streaming upload with a `413` size gate;
  downloads streamed through the API (never a presigned URL) behind the failed-validation
  acknowledgment gate, `410` once the output bytes expire; a paginated conversion history; and
  **reports outlive bytes** — input and output expire on independent per-prefix lifecycle windows
  while `GET /v1/conversions/{id}` still serves both reports. Rate limiting (`429` + `Retry-After`),
  a concurrent-job cap, and optional static-API-key auth.
- **OpenAPI contract artifact (M25).** The `/v1` schema is generated deterministically
  (`python -m backend.openapi`) and committed as `docs/openapi.json`; a drift-guard test regenerates
  and diffs it, starting the paper trail the v1.0 freeze will check against. `info.version` is pinned
  to the source `__version__` so the artifact is a function of the source, not of stale editable
  metadata.
- **Recovery feedback aggregation (M25; Part 5 §7).** `(scenario, choice, parameters) → validation
  status` aggregated over persisted rows (`backend.jobs.feedback`) — **read-only and metadata-only**
  (no file contents, no report bodies), realized as a Python aggregation rather than a SQL view to
  keep SQLite/PostgreSQL parity. Logging only: no default ever changes because of these statistics
  (P4 is untouchable by construction), and surfacing is deferred to the Web UI.
- **Tier 1 compose stack finalized (M25).** `docker compose up --wait` yields the full upload →
  inspect → convert (pause/resume) → validate → download loop locally, expiry included, with a
  backend **readiness** healthcheck so the worker and CI wait for migrations rather than a
  merely-started process.
- **CI (M25).** The backend suite runs in the per-PR `ci.yml` gate; a new `main.yml` spins the real
  compose stack and drives the worked example over HTTP end to end (`tests/integration`, marker
  `integration`, skipped unless `XTALATE_LIVE_BASE_URL` is set), then builds and pushes the single
  service image (API + worker share it) to GHCR tagged `main-<sha>`.
- **Docs.** `docs/API.md` gains a Service (HTTP API) section with a full `curl` walkthrough; the
  README adds the service story and an HTTP quickstart (the library/CLI story unchanged);
  `.env.example` documents every setting.

### Fixed — the v0.5 architectural review

Folded into 0.5.0 before the tag (the review-inside-the-version rule, `docs/private/DECISIONS.md`
D64); see D85–D89 and MASTER_SPEC Revision 1.23.

- **`upload_reference` recovery works over HTTP (D86).** The pause advertised a `reference` file_id,
  but the worker handed that string to the Recovery Engine, which needs a *parsed* structure (the
  CLI parses `file=PATH` and injects it; the service did not) — so every `upload_reference` choice
  failed. The worker now resolves a reference file_id into a parsed canonical object before the
  parse/convert consume it; an unknown/expired/unparseable reference is `INVALID_RECOVERY_CHOICE`.
- **A cancel racing a `running` job no longer leaves contradictory artifacts (D86).** Under the RQ
  worker a cancel could land while a conversion was mid-flight; the worker had already persisted the
  conversion, its reports, and output bytes, then crashed on the illegal `cancelled → completed`
  edge — violating "a cancelled conversion produces no output and no Conversion Report." The runner
  now detects the lost race at its completion boundary and discards what the run persisted.
- **`/v1/capabilities*` and `/v1/limits` are public (D85).** They were auth-gated, but the spec makes
  the Capability Matrix public and `/v1/limits` unauthenticated (a pipeline pre-checks them before it
  authenticates); they are now rate-limited but never require a static key.
- **Error codes align to the Part 6 §6 table (D85).** The request-validation envelope is
  `MALFORMED_REQUEST` (was `INVALID_REQUEST`); the capabilities 404 is `FORMAT_NOT_FOUND` (was
  `UNKNOWN_FORMAT`, a 422 sniff-failure code). The `LimitsResponse`/§5 rate+retention surface is
  reconciled in the spec to the single per-minute limit and two retention windows that shipped.
- **Internal soundness (D87).** Removed a state-machine-bypassing `Repository.set_job_state`; moved
  the output-name helper out of the worker; made the upload handler a threadpool `def` (it ran
  blocking I/O on the event loop); made the in-memory rate limiter sweep stale buckets so its bounded
  memory is real.
- **D-log backfill (D88, D89).** The review found M24 and M25 had shipped with no decision-log entry
  (the log jumped from D84 to the review); their decisions are now recorded — D88 for the M24
  bytes/records surface, D89 for the M25 hardening/OpenAPI/feedback/CI choices.

### Notes

- The v0.5 service runs in **anonymous mode** only — optional static API keys, no user accounts.
  Authorization is instance-level, never resource-level: a resource is reachable by anyone holding
  its unguessable id, and the account endpoints answer `404 NOT_ENABLED`. Accounts and the Web UI are
  v0.6.
- The canonical schema version is unchanged at `0.1.0`; the `/v1` REST contract is **not** frozen
  until v1.0 (pre-1.0 minors may break).
- Publishing (the git tag, the PyPI upload, and the GHCR release images) remains the maintainer's
  manual release step.

## [0.4.0] — 2026-07-21

v0.4 — **"Phase 1 Complete."** CIF, the seventh and last Phase-1 format, lands read and write:
cell parameters, symmetry expansion from the operations a file declares, occupancy and formal
charges, and an exporter that writes every atom explicitly under an identity symmetry loop. With it the format set the roadmap called Phase 1 is closed, and
the claim that adding a format is O(1) in the existing formats has now been paid three times.

The version ends where a CIF parser has to end — against real files. A corpus of Crystallography
Open Database entries, vendored verbatim and governed like the golden one, found two reporting
defects that seven milestones of synthetic fixtures had not.

### Added

- **CIF core parser — M17 (`docs/private/DECISIONS.md` D65, D66).** The seventh and last Phase-1
  format begins landing, read side only (the exporter is M19). This version reads **full-cell**
  files: `P 1`, or a file whose symmetry loop holds nothing but the identity. Covered: multi-block
  files (the first `data_` block is the structure, every further block is **named** in a warning —
  blocks are independent structures, not frames); cell *parameters* → lattice vectors in the
  standard orientation, with fractional → Cartesian at the parser boundary and
  `original_coordinate_system = "fractional"` recorded; `_atom_site` loops with type-symbol
  laundering (`Fe3+` → `Fe`, raw symbol preserved per-atom for M19); format-defined `pbc=(T,T,T)`
  as a `parse_notes` entry, never assumed; legacy `_symmetry_*` and modern `_space_group_*` tag
  spellings both recognised; bare `?`/`.` read as **absence** rather than as values (**P3**);
  standard uncertainties (`5.4310(2)`) read as the value; and every unmapped `_atom_site` column
  (occupancy above all) and block tag carried verbatim under `cif:` keys, never dropped.
- **The CIF reader is built as four replaceable stages (D65)** — lexer → document → validator →
  builder — the first parser shipped as a package rather than a module. The stage-2 document type
  is deliberately shaped like `gemmi.cif`'s `Document`/`Block` API so a future gemmi-backed reader
  replaces stages 1–2 without touching the validation rules, the `ParseError` contract, or the
  builder. Two new `import-linter` contracts make the ordering and the "syntax stages know nothing
  of the Canonical Model" rule machine-checked rather than conventional.
- **A CIF needing symmetry expansion is refused, never read as a partial structure (D66).** A file
  declaring a non-`P 1` symbol with **no** operation loop raises `CIF_UNEXPANDABLE_SYMMETRY` —
  permanently, because supplying the operations from space-group tables would be data the file
  never declared (**P4**); expansion-from-symbol belongs to a future `missing_symmetry_operations`
  Recovery Workflow. A file that *does* declare its operations is expanded (see below). The refusal
  exists so a conversion never silently yields a fraction of the atoms — wrong stoichiometry
  behind a plausible-looking output file.
- **Symmetry expansion applies the operations a CIF declares (M18, D67).** Operation strings are
  parsed into exact affine maps over `Fraction`, never floats, so a translation written `1/3` is a
  third; an operation that cannot be read exactly — or whose rotation is not crystallographic
  (determinant ≠ ±1), or a loop omitting the identity — is a `ParseError`, never a silently
  skipped operation. Sites on a symmetry element are merged within **0.05 Å**, judged as a
  minimum-image *physical* distance rather than a fractional tolerance, and merging is scoped to
  one site's orbit so partially-occupied sites sharing a position are never collapsed. Coordinates
  the expansion *generates* are wrapped into the unit cell; coordinates the file *declared* are
  carried exactly as spelled. `parse_notes` records the operation count, the per-site
  multiplicities and the merge count — so `sites × operations − merged = atoms` is checkable from
  the report — and the declared operation strings are carried verbatim in
  `simulation.extra["cif:symmetry_operations"]`. The expansion is anchored on structures whose
  answers are published independently of this code: **NaCl** (`F m -3 m`, 2 sites and the full
  192-operation group expanding to the 8-atom conventional cell, Z = 4) and **rutile TiO₂**
  (`P 4_2/m n m`, 16 operations, Ti on a multiplicity-2 site and O on a multiplicity-4 site
  giving 6 atoms, Z = 2), alongside the existing `P 1` case whose expansion is the identity.
- **Scientific invariants run over the expanded structures (`tests/_invariants.py`, Part 8 §1.3).**
  Stoichiometry is asserted as the published formula-unit count Z; cell volume is cross-checked
  between the constructed lattice vectors and the source's own cell parameters (two independent
  derivations, so a transposed construction cannot satisfy both); and the minimum interatomic
  distance is checked against each structure's known nearest-neighbour contact, which is the
  assertion a special-position merge that failed to fire cannot survive. A deliberately truncated
  operation list is kept as a test that these have teeth — and it demonstrates why the assertion
  is Z rather than a formula, since the truncated cell is still exactly TiO₂ by element *ratio*
  while holding half the atoms the crystal has.
- **Occupancy under its spec-named key, and declared formal charges (M19).** `_atom_site_occupancy`
  is read into `user_metadata.custom_per_atom["cif:occupancy"]`, and a file holding any site below
  full occupancy says so in `parse_notes` — an occupancy the Canonical Model has no first-class
  field for is still a physical claim, not an annotation. Unknown occupancy (`?`/`.`) counts as
  partial: silence is not a claim of full occupancy (**P4**). Formal charges are read into
  `electronic.charges` from the `_atom_type_oxidation_number` loop, joined to sites by
  `_atom_site_type_symbol` — the type symbol is the *join key*, not the source, so a `Fe3+`
  spelling alone does not populate the field. The raw symbol stays carried per-atom either way, so
  the laundering that makes `Fe3+` an `Fe` atom loses nothing.
- **Partial occupancy is warned about in the Conversion Report, for every target (M19).** Dropping
  an occupancy column is not an ordinary annotation loss: a site written without an occupancy reads
  as *fully occupied*, so the output asserts a structure the source never described. The `removed`
  entry says the column was not carried; it does not say the physical claim changed — now both are
  reported (**P5**). The gate is a capability declaration rather than a format list: a target
  suppresses the warning by **naming** `cif:occupancy` in `writable_custom_keys`. A generic
  per-atom passthrough does not qualify, since it carries the numbers as an unlabelled column
  nothing downstream reads as occupancy.
- **CIF exporter — the write side, in `P 1` with every atom explicit (M19, D68).** Cell parameters
  from the canonical lattice vectors, `_atom_site` rows in fractional coordinates, and the block
  tags the parser carried through written back to the tags they came from. `max_frames = 1`, so a
  trajectory reaches it only after the Conversion Engine has recorded the reduction as an
  Assumption. The Canonical Object holds the *expanded* cell (D67), so the only symmetry true of
  the coordinates being written is the identity, and the file states exactly that: a one-entry
  symop loop and **no space-group symbol at all**. A source `cell.space_group` is declared `NONE`
  and reported `removed`. Writing `P 1` alongside the loop was tried and rejected — re-parsing
  recovered a value the report had called absent, and a symbol Xtalate supplies makes the output
  assert what no input stated. CIF is also the first target to *represent* occupancy, so the
  warning above is suppressed for CIF targets with no edit to the pre-flight diff (**P6**).
- **CIF is enrolled in the round-trip matrix, and the export side is externally anchored (M19).**
  The `P 1` hexagonal case joins the golden sources — the one fixture whose native coordinates are
  fractional against a non-orthogonal cell (γ = 120°), so every hop out of it exercises the
  fractional → Cartesian boundary against a lattice where a sign or transpose error cannot hide.
  The exported files are checked against the same published numbers the parse side uses: rock salt
  must come back as 8 atoms, Z = 4, nearest Na–Cl at 2.8201 Å. The CIF identity round-trip is
  deliberately lossy by exactly one field (the space-group symbol, per D68), and that set is
  **derived from the Capability Matrix** rather than hand-listed, so a future change that dropped
  something else — or stopped declaring the drop — fails.

- **A real-world corpus, governed like the golden one but expected differently (M20, D70).**
  Crystallography Open Database entries (CC0) are vendored verbatim under `tests/wild/`, a second
  corpus root sharing `tests/golden/`'s governance module — same manifest schema, same `sha256`
  tripwire, same *no manifest, no license, no merge* rule, one generated `ATTRIBUTIONS.md` across
  both. What differs is the expectation, because a golden expectation is *hand-verified* and
  nobody can attest to 192 expanded coordinates. A wild case instead declares the **exact** set of
  `ParseIssue` codes the file must produce — equality, so a code that appears untriaged and a code
  that silently stops appearing both fail — and its stoichiometry is checked against
  `_chemical_formula_sum` × `_cell_formula_units_Z` read straight from the source text with a
  regex that shares no code with the parser under test. The file is its own oracle: a symmetry bug
  that produces the wrong atom count is caught by contradicting the very file that produced it,
  with nobody having to know the right answer in advance. Skipping that check requires naming a
  reason from a fixed vocabulary *and* arguing it in prose, and the suite checks the skip against
  the file. Ten entries span the axes M20 named — legacy `_symmetry_*` spelling, mixed-case tags,
  `?`/`.` markers, uncertainty parentheses, occupancy < 1, oxidation-state symbols — several
  carrying more than one, as real files do. Multi-block is not among them and could not be: COD
  serves one structure per file, and ~60 entries sampled across its numbering space held no second
  `data_` block. That is recorded in the corpus rather than left to look like an oversight.

### Fixed

- **The occupancy warning carried two claims that are true of different files (M20, D71).**
  `CIF_OCCUPANCY_NOT_MODELLED` fired whenever `_atom_site_occupancy` was present — correct, since
  the column is an unmodelled schema gap whatever its values — while its message claimed the file
  "states partial site occupancy", which was false for most files it fired on. COD writes that
  column on nearly every entry, so the warning was on track to fire almost universally while
  saying something untrue almost as often, which trains a reader to skim past the file where
  occupancy really is partial. The trigger is unchanged (suppressing it would trade a misleading
  warning for a silent loss, the worse failure under **P5**); the wording now states only what is
  true of a carried column, and the disorder claim moves to a new **`CIF_PARTIAL_OCCUPANCY`**,
  raised only when some site's occupancy is not 1 — with unknown (`?`/`.`) counting as not-1,
  since silence is not a statement of fullness (**P4**). The predicate deciding that moved to
  `schema/paths.py` beside the key it interprets, because the parser cannot import the pre-flight
  layer that owned it and a second definition of "full" would be free to drift.
- **Precision loss on cell parameters was reported nowhere (M20, D71).** A parenthesized standard
  uncertainty (`4.217(1)`) is read as its value and its precision digits discarded, and
  `parse_notes` said so — but only for coordinates, because the note was emitted from the
  coordinate reader alone. Real refinement is the other way round: a lattice constant essentially
  always carries an esd while an atom on a special position is written as an exact `0.` or `0.5`,
  so the note covered the rare case and missed the universal one, silently, for three milestones.
  `validate_cell` now returns the cell tags that carried an uncertainty and the builder folds them
  into the same note. A synthetic fixture could not have found this — a fixture author
  demonstrating uncertainty parentheses puts them on a coordinate, and the golden corpus did.
- **The package version was declared three times and nothing compared them (M20).** `pyproject.toml`
  names the version the artifact carries, `xtalate.__version__` is what the code reports, and a
  smoke test pinned a third copy as a literal — so a release bump edited two lines in one file and
  the suite stayed green while the two real declarations disagreed. This is not only a metadata
  nit: `__version__` is stamped into `provenance.history[].tool_version` on every object Xtalate
  produces, so the drift would attribute every converted file to the wrong tool version. The
  literal is replaced by a check that `__version__` equals the version in `pyproject.toml`, read
  from the file rather than from installed metadata (which goes stale in an editable checkout —
  it reported a third number again during this fix).
- **A stale claim in the occupancy note, caught in passing (M20, D71).** It ended "No Phase 1
  export target can represent it", true when M19 wrote it and false once M19's own CIF exporter
  declared `cif:occupancy` writable. Nothing tested the sentence: prose inside a note is pinned
  byte-exact by the golden expectations, which catches *changes* to it and never its *truth*.
- **extXYZ and ASE `.traj` over-declared what they can write to `user_metadata.custom_per_atom`,
  and a format may now declare its writable custom keys as a *name pattern* (D69).** Enrolling CIF
  in the round-trip matrix made it the first golden source carrying per-atom carry-through columns,
  which surfaced two latent over-declarations no previous format combination could reach.
  - **extXYZ was producing unparseable output, not merely lossy output.** The `Properties=` grammar
    separates its fields with `:`, so a format-scoped key such as `cif:occupancy` was written as
    `...:cif:occupancy:R:1` and the resulting file did not parse at all — while the Conversion
    Report claimed the column preserved. The container is now `PARTIAL`, and the writable set is
    declared as the pattern `extxyz:<name>`: extXYZ writes arbitrary columns, so the set cannot be
    enumerated, but its parser re-prefixes every column it reads, making `extxyz:<name>` exactly
    the set that survives write → read under its own name. Keys outside it are reported `removed`
    in pre-flight, and the exporter guards the same pattern for direct (non-engine) calls.
  - **ASE `.traj` persists no custom per-atom array under any name**, so it gets no pattern — the
    container is declared `NONE`, reported `removed`, and no longer set on the `Atoms` object at
    all, so the code says the same thing the capability does. Per-frame metadata (`atoms.info`) is
    unaffected.
  - **New capability field `writable_custom_key_pattern`** (`{container_path: regex}`), applied by
    the pre-flight in the same place and the same way as `writable_custom_keys`. A container
    declares a list or a pattern, never both; a pattern that does not compile, or that competes
    with a list, is rejected when the plugin *registers* rather than on some later user's
    conversion. The Capability Matrix stays static, inspectable data — consulting the exporter at
    pre-flight time was considered and rejected on exactly that ground.

### Changed

- **Documentation: architectural-review changelog attributions corrected to match each release's
  tag and published artifact, and the versioning policy recorded (`docs/private/DECISIONS.md` D64).** Each
  version's post-release architectural review is folded into that version before tagging, not
  deferred to the next. The post-`0.2.0` review (D53–D55, golden-corpus governance hardening, the
  velocity-bearing corpus case, and internal de-duplication) now sits under **[0.2.0]** — the tag
  and PyPI artifact that actually contain it — and the post-`0.3.0` review (D62–D63, the XDATCAR
  Cartesian-scale fix, and the CLI plugin-error surfaces) under **[0.3.0]**. No code changes; the
  released `0.2.0` / `0.3.0` artifacts are unaffected. (v0.1 predates the policy — its review first
  shipped in the `0.2.0` artifact.)

### Fixed — the v0.4 architectural review

Per the versioning policy (`docs/private/DECISIONS.md` D64) a version's own post-release review
ships **inside** it, so these land in `0.4.0` rather than a later release. The CI gates were green
throughout; none of the below is a gate failure, which is the point of running the review against
real files and the release checklist rather than against the suite.

- **A written CIF no longer re-asserts the space group it deliberately withheld
  (`docs/private/DECISIONS.md` D72).** D68 suppresses the Hermann-Mauguin and Hall symbols so the
  output cannot claim a setting its expanded coordinates no longer encode — and
  `_space_group_IT_number` reached the file anyway, through `simulation.extra` carry-through. IT
  number 225 *is* `Fm-3m`: every CIF written from a symmetric source carried a 192-operation group
  above an already-expanded atom list declaring only the identity, and a standards-compliant reader
  honouring it expands a second time and gets four times the atoms. Worse, the Conversion Report
  said `cell.space_group` had been *removed*, so the report was false rather than merely
  incomplete. The hold-back is now over space-group **identification** — the IT number and any
  database's own symbol spelling (COD writes `_cod_original_sg_symbol_H-M`) — while a tag naming
  only the crystal system is kept, because that stays true of the written cell.
- **CIF → CIF is idempotent again for hexagonal, trigonal and rhombohedral cells (D73).** The
  parser's exact-angle table (M17) had no inverse on the write side, so a `120.0` cell came back
  `120.00000000000001`, missed the table on the next read, and reintroduced exactly the spurious
  tilt the table exists to prevent.
- **Non-finite numerics stay inside the parse-error contract (Part 3 §5).** `float()` accepts
  `"nan"`, and NaN then defeats every ordinary range guard downstream, so the failure surfaced two
  stages later as an uncaught `pydantic.ValidationError` — a stack trace and exit 1 where a
  structured parse error exits 4.
- **Two readable files are no longer refused with a misleading cause (D74).** A leading
  `data_global` block — standard in CCDC/CSD depositions — made the reader take the first block and
  refuse with `CIF_MISSING_CELL`, naming a missing cell parameter that sits three lines further
  down; the structure block is now the first one carrying an `_atom_site` loop. And unquoted
  symmetry operations containing spaces hard-failed, because the ragged-loop guard is vacuous for a
  single-column loop (`len(values) % 1` is zero for any count); they are now rejoined, but only
  where every value becomes a complete triplet, so a genuinely malformed operation still reports
  itself rather than being mangled into its neighbour.
- **The exporter writes what it holds.** A literal quoted `'?'` was re-emitted bare — which is
  CIF's *unknown* marker, so a value the source stated became an absence. And the per-column
  fallbacks used `or`, which tests truthiness: an all-`None` column is a non-empty list, so a
  source whose `_atom_site_type_symbol` was `?` on every row had every atom written `?` while
  `atoms.symbols` held good elements. Both fallbacks are now per atom.
- **A block name the CIF grammar cannot spell is refused, not silently truncated (D75).**
  `cif:data_block_name` is declared writable, so the pre-flight reported it *preserved* — while the
  writer truncated at the first space. A D69 over-declaration drops a value; this substituted a
  different one and still called it preserved. An absent name still synthesizes `xtalate`.
- **CIF's `parser_version` no longer drifts from every other format's (D75).** It passed a class
  attribute hardcoded `"0.4.0"`, which equalled the package version and so read correctly while
  meaning something different; at `0.5.0` every other format would have moved and CIF alone would
  have gone on claiming `0.4.0` in shipped provenance.
- **Lattice geometry has one home and one exact-angle table (`schema/cell.py`, D77).** The
  parameter↔vector inverse pair was split across the parser and exporter layers with no shared
  table, which is what allowed the angle defect above; `to_fractional` was separately copy-pasted
  verbatim between two exporters.
- **D24's fractional lattice-scaling claim is withdrawn (D76).** It recorded the Part 5 §4.2
  formula as "implemented but unexercised"; there is no lattice term in the code, and two
  fractional-native exporters have since landed. The branch stays unimplemented — every Phase 1
  exporter writes full round-trip precision, so no bound is ever non-zero — but the case now
  refuses rather than silently applying a tolerance roughly `|L|` times too tight. Relatedly, the
  per-path representational bound was never recorded, so offline re-thresholding had been silently
  tightening `numeric_field_fidelity` while the scalar checks re-applied theirs correctly.
- **`Ow1` reads as oxygen, and the label fallback stops inventing `X` (D78).** The site-label regex
  is greedy over two letters and a regex alternation does not backtrack, so `Ow1` — the
  conventional water-oxygen label, ubiquitous in hydrate CIFs — raised `CIF_INVALID_SYMBOL` on a
  file whose element is unambiguous. Element case normalization now lives beside the element table
  rather than only in the CIF parser. A site that genuinely resolves to the reserved `X` now warns,
  which `schema/elements.py` has required since M1 and no parser implemented.
- **CIF joins the curated PR round-trip pairs.** It was in neither curated set, so every CIF pair
  ran nightly-only and the format never appeared in the three-hop suite — the only backstop against
  a wrongly-declared capability, since the two-hop diff derives its expectation from the same
  Capability Matrix that drove the conversion. `cif↔poscar` is the pair added, because it is the
  only CIF pair whose comparable subspace contains `cell.lattice_vectors`.
- **Documentation caught up with what v0.4 shipped.** `docs/API.md` and `docs/ARCHITECTURE.md` both
  still said CIF "is not yet implemented"; the shipped package docstring still described v0.3; the
  README described the `P 1` export policy D68 had rejected; `CITATION.cff` still said `0.3.0`.
  MASTER_SPEC received the four Revision notes v0.4's own standing rule required and had not
  written (1.17–1.20, plus 1.21 for this review), which is also where footnote 11's two false
  occupancy clauses, footnote 13's blank merge threshold, and three stale capability rows were
  corrected. The §3 table's claim to be kept in sync with the declarations by a test is
  **withdrawn**: no such test exists, none can now that the document is private, and the premise
  was wrong anyway — the table describes a *format's* expressiveness, a declaration describes
  Xtalate's read and write capability, and the two are not derivable from each other.
- **User-facing report text no longer cites a document readers cannot open.** Ten capability notes,
  `lossy_notes` and parse notes named `DECISIONS.md` by bare filename; the design docs became
  private in v0.3. Docstrings keep their citations — contributors have the file.

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

[Unreleased]: https://github.com/jsong1218/Xtalate/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/jsong1218/Xtalate/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/jsong1218/Xtalate/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/jsong1218/Xtalate/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jsong1218/Xtalate/releases/tag/v0.1.0
