# Xtalate v1.5.0 — Release Notes

> **Status: draft.** Prepared at the M58 cut line for the maintainer to attach to the GitHub
> release at tag time (D52). Nothing here is published until the maintainer tags and releases —
> `git tag v1.5.0` and the PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 1.0.0

**Package `1.5.0` · schema `1.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance and
bumps on this release; the canonical `schema_version` bumps only behind a real migration. This
release ships **no schema change** — a dataset is a container of ordinary reports, never a new
model — so the mandatory `Schema version:` line above reads `1.0.0`, not `1.5.0`. A schema number
that incremented without a schema change would be a version that lies; the honest statement is a
package bump on a frozen schema.

## What's new in 1.5.0

- **The roadmap's dataset stopping point, shipped.** A directory of real simulation outputs
  (VASP `vasprun.xml`/`OUTCAR`, Quantum ESPRESSO `pw.out`, LAMMPS dumps, …) becomes **one
  validated MLIP training set with one aggregate record** — at the library
  (`run_batch`), on the CLI (`xtalate convert --batch manifest.yaml -o train/`), over HTTP
  (`POST /v1/batch/convert`), and in the browser (the batch record on the job page). The
  stopping point runs for real at fixture scale in
  [`examples/batch_assemble_training_set.py`](examples/batch_assemble_training_set.py): a mixed
  VASP/QE/LAMMPS manifest assembles into one extXYZ training set, with the honest variable-N
  note stated aloud. **Aggregation, never curation** (roadmap §11): no selection, splitting, or
  deduplication — *"Batch operations (v1.5) convert what they are given, completely and
  reported."* Every per-file `ConversionReport`/`ValidationReport` is embedded **verbatim** in
  the aggregate (the same file converted alone and inside a batch serializes byte-identically),
  and the tallies are counts, never restatements — so a batch cannot elide a per-file loss.
- **The `batch_convert` API job kind (M58).** `POST /v1/batch/convert` takes ordered `file_id`s
  + one target and fans out to **ordinary child convert jobs**, each a navigable record with its
  own pause, refusal, and expiry. The parent completes only when every child is settled; a child
  that needs a decision pauses on its own record (per-file consent stays per-file — the batch
  never answers a recovery question wholesale), and the envelope's additive `children`
  projection keeps the record navigable in every state. The Web UI renders the parent's tallies
  plus links into each child's record (navigable, not novel).
- **The ASE `.db` database, read and write (M55).** The third ASE-backed format and the first
  multi-structure dataset container. A single-row `.db` is one structure; a **multi-row** `.db`
  is a dataset, never a trajectory — it refuses on the single-file path with the recoverable
  `ASEDB_MULTIPLE_ROWS` and **fans out** under `--batch` into N ordinary per-row conversions.
  `assemble` builds one N-row `.db` from N sources, so `extxyz ↔ ase_db` dataset translation is
  symmetric.
- **DeePMD-kit NumPy systems, read and write (M56).** The first *directory* format:
  `deepmd_npy` reads and writes a DeePMD system directory (`type.raw`, `set.000/coord.npy`, the
  label arrays), with the virial a recorded deterministic mapping (`virial ↔ stress` via
  stress·volume, hand-computed golden) and the `set.000`/`set.001`/… train/test sharding
  concatenated on read with the dropped partition **reported** — never silently discarded, never
  emitted on write. `assemble` to `deepmd_npy` groups a mixed-composition batch **by
  composition** into N systems.
- **The pymatgen in-memory adapters (M57).** `xtalate.adapters.from_pymatgen`/`to_pymatgen`
  translate between pymatgen objects (`Structure`/`Molecule`) and the Canonical Object in one
  process — a library seam, **not** a registered format (no file, no sniffer entry, no CLI
  subcommand), behind the optional `xtalate[pymatgen]` extra. `to_pymatgen` dispatches on `cell`
  presence — periodic → `Structure`, cell-less → `Molecule`, never a fabricated identity lattice.
- **Measured performance, reported not gated (M58-S3).** Two new Part 8 §4 benchmark rows —
  `batch_convert_100_files` (100 files through `run_batch`; the aggregate's footprint pins the
  reports-never-frames boundary) and `parse_asedb_1k_rows` (a 1,000-row `.db` read to the honest
  `ASEDB_MULTIPLE_ROWS` refusal) — run under `python -m benchmarks`.

The four lockstep version sync points (`pyproject.toml`, `__version__`, `CITATION.cff`, the
regenerated `docs/openapi.json`) read `1.5.0`; `frontend/package.json` is deliberately not a sync
point (untouched since the v1.0 flip). Tag and publish remain the maintainer's manual,
nightly-green-gated step (D52).
