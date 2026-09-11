# Xtalate v1.7.0 — Release Notes

> **Status: draft.** Prepared for the maintainer to attach to the GitHub release at tag time (D52).
> Nothing here is published until the maintainer tags and releases — `git tag v1.7.0` and the
> PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.7.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. v1.7 is
**API-additive + CLI + UI** — a closed set of four repair operations, adding **zero fields** to the
Canonical Object — so the mandatory `Schema version:` line above reads `1.0.0`, not `1.7.0`.
`operation="repair"` was reserved vocabulary in the 1.x schema all along; activating a documented
reserved value changes no shape, and a schema number that incremented without a schema change would
be a version that lies. The honest statement is a package bump on a frozen schema.

## Added

* **The repair engine (M64).** A Canonical Object can now be modified on request, between parse and
  pre-flight, through the `RepairOperation` contract (`src/xtalate/repair/`) — a pure, deterministic
  Canonical→Canonical transform recorded with the D249 triple (an Assumption carrying the operation
  and its complete parameters, a plain-language statement of what changed, and a
  `ConversionRecord(operation="repair")` in Provenance). Repairs are all-or-nothing (one blocked op
  refuses the whole set with nothing applied) and ride the ordinary Conversion Report — one pipeline,
  one report schema. The hazard taxonomy gains a fourth, **transformative** class: a repair that
  changes values in place and loses the originals carries the same consent discipline as reductive
  loss — explicit request **plus** a `ReportWarning(source="repair")` naming exactly what is
  unrecoverable. Flagship op lands first: **wrap-into-cell** (`wrap_into_cell`), the minimum-image
  fold with the `WRAP_DISCARDS_UNWRAPPED_PATHS` warning; a cell-less object refuses through the
  existing `missing_lattice` recovery — wrap invents no box (D249–D251).
* **Center, deduplicate, species reorder — the set closes at four (M65).** The remaining three ops on
  the same engine over a shared per-atom reindex spine (`repair._reindex`). **Species reorder**
  (`species_reorder`) regroups atoms by element in first-appearance order via one frame-invariant
  permutation (non-destructive — the recorded map recovers the original order; `ATOM_ORDER_CHANGED`
  suppressed on a no-op); **center** (`center`) translates a stated reference
  (`centroid`/`cell_center`) to a stated target (`origin`/`cell_center`/explicit `[x,y,z]` Å) — both
  required, no default (P4) — positions only, with `CENTER_DISCARDS_ABSOLUTE_POSITION`; **deduplicate**
  (`deduplicate`) removes atoms closer than a user-supplied `distance_threshold` (no default), lowest
  original index surviving each cluster, survivor values kept verbatim (never an averaged pseudo-atom),
  minimum-image only along the axes the cell **declares** periodic (a cell's presence is not
  periodicity, P3), the Assumption enumerating the removed atoms by `{index, species}`. The closed set
  is the "not a molecular editor" boundary (D252–D254).
* **The CLI, API, and UI surfaces (M66).** The same closed set from every surface — the CLI's
  repeatable `--repair OPERATION[,param=value…]` flag (applied in argument order — order is scientific
  meaning), the additive `repairs` field on `POST /v1/convert`'s options (an ordered list of
  `{operation, parameters}`, parameters required up front; a malformed repair is a clean
  `MALFORMED_REQUEST`), and the Web UI's **repair card** in the pre-conversion step (add, parameterize,
  remove, order — the list *is* the applied order), repair rows marked **⟳ "Modified on request"**, a
  blue mark deliberately distinct from the ◆ violet assumption mark because a transformed coordinate is
  not a fabricated one. The `⟳` mark is the milestone's one new vocabulary artifact; the schema stays
  `1.0.0` (D255–D257).
* **The property suite and the release (M67).** The contract — *every repair is reproducible from its
  report alone* — proven at property scale (`tests/property/test_repair_properties.py`): wrap
  idempotence, dedupe removal-exactness, species-reorder permutation validity, and report
  reconstruction (a fresh conversion re-derived from the recorded Assumption parameters alone yields
  byte-identical output), under the `pr`/`nightly` hypothesis profiles. Package reaches `1.7.0` on
  schema `1.0.0` (D258–D259).

## Changed

* **In-place repair recovery — a resumed blocked repair resolves in place (D260).** A repair that
  blocks (a cell-less `wrap_into_cell`, a `cell_center` center) now resolves through a pre-supplied
  recovery choice instead of refusing unconditionally — the engine applies the block scenario's choice
  to the object first (recorded as a recovery Assumption with the caller's origin, `preset` or `user`),
  then retries the repair against the recovered object. All-or-nothing is preserved (a repair still
  blocked after a supplied recovery refuses with the pre-repair Assumptions carried), and a lattice
  fabricated only for a target that cannot store it (a wrap on plain XYZ) is audited in `supplied`
  without entering the write plan (D47). The `--recover missing_lattice=…` preset now finishes the job
  instead of re-pausing with the same block.
* **Wrap fold clamped to `[0, 1)` at every precision, R5 warning made conditional (D258→D260).**
  `wrap_into_cell`'s fold (`np.mod(frac, 1.0)` with a `1.0 → 0.0` clamp) is idempotent even within
  float-underflow of a cell face (a coordinate below the ULP of 1.0 previously folded onto the face and
  flipped to `0.0` on the next wrap), and `WRAP_DISCARDS_UNWRAPPED_PATHS` fires only when the
  application actually moved positions — a no-op wrap discards no trajectory information, so the
  statement would be a lie (the dedupe/reorder precedent).

## Fixed — the v1.6/v1.7 architectural review

* **Wrap now folds only periodic axes (D261).** `wrap_into_cell` folds the axes the cell declares
  periodic and leaves the rest, mirroring deduplicate (a cell's presence is not periodicity, P3) —
  previously it folded all three regardless of `pbc`. Carries the wrap flagship e2e on a genuine
  out-of-cell fixture (REPAIR-C1, REPAIR-E1).
* **A no-op wrap or center no longer claims a loss (D262).** The transformative warning and hazard are
  suppressed when the application moved nothing (within the 1e-9 Å position tolerance), matching the
  deduplicate/species-reorder no-op discipline (REPAIR-H1, REPAIR-H2).
* **Recovery previews describe the repaired document (D263).** The pre-flight and recovery-preview
  seams (`preflight`/`preview_recovery`) thread the requested repairs best-effort, so the preview
  reflects what will actually be written rather than the raw parse (REPAIR-H3).
* **Geometry endpoints harden under load (D264).** The frame window is capped mid-stream — an over-cap
  request is `422 FRAME_LIMIT_EXCEEDED`, never a silent clamp — swept bytes answer `410` at every
  call-site, the server-side `GeometryCache` is guarded by a `threading.Lock`, and the heap
  byte-estimate uses an honest ×4 factor (GEO-H1, GEO-H2, GEO-M1, GEO-L1).
* **One Mol\* mount across expand and theme, legacy bookmarks follow the history cursor (D265).** The
  viewer keeps a single stable canvas node through expand/fullscreen and reconciles the theme in place
  on a live flip (never a re-mount), and a legacy bookmark walks the keyset history cursor (capped at
  50 pages) instead of assuming a fixed page (VIEW-H1, VIEW-M1, VIEW-M2).
* **Security dependency bumps (D266).** `next` → 15.5.25 (RCE advisory), `sharp` 0.35.4 / `qs` 6.16.0 /
  `js-yaml` 4.3.2 via `npm audit fix` (no `--force`); the two remaining moderates are the dev-only
  vitest-chain advisories, deferred (DEP-C1, DEP-H1, DEP-M1).

Full Changelog: [v1.6.0...v1.7.0](https://github.com/jsong1218/Xtalate/compare/v1.6.0...v1.7.0)

The chained version sync points (`pyproject.toml`, `__version__`, `CITATION.cff`, the regenerated
`docs/openapi.json`) read `1.7.0`; `frontend/package.json` is deliberately not a sync point (untouched
at `1.0.0` since the v1.0 flip, v1.5/M58 precedent). Tag and publish remain the maintainer's manual,
nightly-green-gated step (D52).
