# Xtalate v1.7.0 — Release Notes

> **Status: draft.** Prepared at the M67 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.7.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.7.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release is **File Repair** — explicit, chosen, recorded modification, never silent fixing — and it
is **API-additive + CLI + UI**: it adds **zero fields** to the Canonical Object, so the mandatory
`Schema version:` line above reads `1.0.0`, not `1.7.0`. `operation="repair"` was reserved
vocabulary in the 1.x schema from the start; activating a documented reserved value changes no
shape, and a schema number that incremented without a schema change would be a version that lies.
The operation set is **closed at four**, and repair is never automatic — nothing is modified unless
the user asks, and no report ever says "fixed".

## What's new in 1.7.0

- **Repair is explicit, chosen, recorded modification — never silent fixing.** A Canonical Object
  can now be modified on request, between parse and pre-flight, through a closed set of four
  operations — **wrap-into-cell**, **center**, **deduplicate**, and **species reorder** — each
  applied in the order asked, each recorded as an Assumption with its complete parameters. The
  version's contract: **every repair is reproducible from its report alone.** The boundary is
  honest: byte-level repair stays with parse-time recovery — a file that cannot become a Canonical
  Object cannot be repaired, only recovered — and the closed set is the "not a molecular editor"
  non-goal, held by enumeration.
- **The repair engine (M64; D249–D251).** The `RepairOperation` contract in `src/xtalate/repair/`:
  pure, deterministic, Canonical Object → Canonical Object transforms applied between parse and
  pre-flight, all-or-nothing, riding the ordinary Conversion Report (one pipeline, one report
  schema) with the D249 record triple — Assumption + plain-language statement +
  `ConversionRecord(operation="repair")`. The hazard taxonomy gains the **transformative** fourth
  class: a repair that loses the originals states exactly what is unrecoverable in a
  `ReportWarning(source="repair")`. The flagship lands first: **wrap-into-cell**, the minimum-image
  fold with deterministic boundary handling, carrying the R5 warning that *wrapping discards
  unwrapped diffusion paths* — and a cell-less object refuses through the existing
  `missing_lattice` recovery, never a fabricated box.
- **The set closes at four (M65; D252–D254).** **Species reorder** regroups atoms by element via
  one frame-invariant permutation (non-destructive — the recorded map recovers the original order);
  **center** translates a stated reference (`centroid`/`cell_center`) to a stated target
  (`origin`/`cell_center`/explicit `[x, y, z]` Å), both required, no default; **deduplicate**
  removes atoms closer than a user-supplied threshold, single-structure only, survivor values kept
  verbatim (never an averaged pseudo-atom), minimum-image only along the axes the cell declares
  periodic, with the removed atoms enumerated exactly in the Assumption. The ordered composition
  (wrap → dedupe → reorder) re-derives byte-identically from the report's Assumption chain.
- **Every surface (M66; D255–D257).** The CLI's repeatable `--repair OPERATION[,param=value…]`
  flag (an ordered list applied in argument order — order is scientific meaning); the additive
  `repairs` field on `POST /v1/convert`'s options (an ordered list of `{operation, parameters}`, a
  malformed repair a clean `MALFORMED_REQUEST`); and the Web UI's repair card in the pre-conversion
  step, with repair rows marked **⟳ "Modified on request"** — a blue mark deliberately distinct from
  the ◆ violet assumption mark, because a transformed coordinate is not a fabricated one — and the
  Compare tab rendering the wrapped before/after from canonical geometry. The `⟳` mark is the one
  new vocabulary artifact of the whole milestone.
- **Proven at property scale, and released (M67; D258–D259).** The reproducibility contract is
  proven over generated Canonical Objects — wrap idempotence, dedupe removal-exactness,
  species-reorder permutation validity, and report reconstruction to byte-identical output — under
  the registered `pr`/`nightly` hypothesis profiles. The package reaches `1.7.0` on schema `1.0.0`.

**One honest limitation (option A, D259):** over HTTP, a cell-less `wrap_into_cell` **refuses and
is not resolvable in place in v1.7** — supply a cell in the source, or omit the wrap. Making a
resumed blocked repair complete (applying a pre-supplied recovery before retrying the repair) is an
engine enhancement deferred to **v1.7.1**, pinned by the renamed API test.

The chained version sync points (`pyproject.toml`, `__version__`, `CITATION.cff`, the regenerated
`docs/openapi.json`) read `1.7.0`; `frontend/package.json` is deliberately not a sync point
(untouched at `1.0.0` since the v1.0 flip, v1.5/M58 and v1.6/M63 precedent). Tag and publish remain
the maintainer's manual, nightly-green-gated step (D52).