# Xtalate v2.0.0 — Release Notes

> **Status: draft.** Prepared for the maintainer to attach to the GitHub release at tag time (D52).
> Nothing here is published until the maintainer tags and releases — `git tag v2.0.0` and the
> PyPI/GHCR/GitHub-release publish are a manual, nightly-green-gated step.

Schema version: 2.0.0

**Package `2.0.0` · schema `2.0.0`.** The two axes move under separate rules (see the README's
*Versioning and stability* section): the package version stamps every conversion's provenance, and
the canonical `schema_version` bumps only behind a real migration. v2.0 is the one release where
**both** axes advance — and for the same reason. The canonical model's constant-N invariant is lifted
behind a genuine `1.0.0 → 2.0.0` migration (each frame now carries its own atom count), which is a
breaking change to the schema *and* to the one place that shape surfaced in stored objects
(`user_metadata.custom_per_atom` relocated onto each frame). That is a major on both axes, stated
once. It is the first schema bump since the v1.0 freeze; it held at `1.0.0` from v1.0 through v1.8.

**If you are upgrading, read the [migration guide](../MIGRATION.md) first.** Its one-line summary: for
most users a major is a `pip install -U`, because stored objects migrate forward on load through the
`0.1.0 → 1.0.0 → 2.0.0` chain, and constant-N conversion output is byte-identical.

## What v2.0 is

v2.0 does not so much add a feature as **retire a refusal**. For five versions the ladder told a class
of users "this trajectory is real and we cannot represent it — here is exactly why" (a `ParseError`
with a `recovery_hint`, never truncation or padding). v2.0 is the payment: grand-canonical,
deposition, reactive, and mixed-composition trajectories — whose atom count changes frame to frame —
become first-class, read and round-tripped per frame, and **H5MD** arrives as the first binary
container that expresses a varying particle number natively. With it, Xtalate represents, converts,
validates, and honestly reports every trajectory class the MLIP era produces — fixed-N and variable-N,
text and binary, file and dataset — with contracts re-frozen at `2.0`.

## Added

* **H5MD read *and* write — the eighth first-party format and the first binary variable-N container
  (M74).** Xtalate reads and writes the community HDF5 interchange layout: `/particles/<group>`
  positions, species, velocities, forces, masses, charges, and box (fixed-in-time or time-dependent,
  cuboid shorthand or full 3×3), plus `/observables`. Its per-step VLEN layout expresses a trajectory
  whose atom count changes frame to frame, so a variable-N source round-trips through H5MD natively.
  Units are laundered at the boundary — a recognized `unit` converts and is recorded in
  `provenance.source_units`; an unknown unit passes through verbatim with an `H5MD_UNKNOWN_UNIT`
  warning; an absent unit passes through without claiming canonical units (**P3**). A file with more
  than one `/particles` subgroup is **refused** (`H5MD_MULTIPLE_PARTICLE_GROUPS`) rather than silently
  narrowed; a torn tail is recoverable via `truncate_at_last_valid_frame`. The parser is frame-lazy
  (peak memory tracks the resident frame, proven at 10⁴ frames), and adds one isolated runtime
  dependency, `h5py`, confined to the H5MD parser/exporter by an import-linter contract.

## Changed

* **Canonical schema major `1.0.0 → 2.0.0`: the constant-N invariant is lifted (M72).** A
  `CanonicalObject`'s frames may differ in atom count; the object-level cross-frame N check is removed
  and each frame validates its own N against its own per-atom arrays.
* **`custom_per_atom` relocated from root `user_metadata` onto each `frame` (M72).** A per-atom
  column's first dimension is a *frame's* atom count, no longer an object-level quantity, so the
  container lives on the frame it describes. `custom_per_frame` and `custom_global` are unchanged and
  stay on root `user_metadata`. The Capability-Matrix / report / `vocabulary.json` category identifier
  stays the string `user_metadata.custom_per_atom`, so constant-N output is byte-identical and the
  published vocabulary is untouched.
* **The engine, SDK, and reports answer "which frame's N?" everywhere (M73).** Validation applies its
  species-reorder permutation *per frame* against each frame's own atom count; the streaming SDK moved
  `custom_per_atom` off `StreamHeader` onto each `StreamFrame.frame`, re-proving the streamed-equals-
  materialized identity theorem under variable N; and the Capability Matrix gained a
  `supports_variable_atom_count` axis so a constant-N target refuses a variable-N source at pre-flight
  with a `frame_selection` offer, before any bytes are written (**P5**).
* **A multi-row ASE `.db` reads through as one variable-N object (M73).** Each row maps to a frame at
  its own atom count; the `ASEDB_MULTIPLE_ROWS` refusal is retired (the single-structure escape hatches
  stay). A mixed-composition `assemble` output re-parses as one variable-N object and is validated
  whole against a stacked reference (`BatchReport.whole_object_validation`).

## Removed

* **Retired the constant-N reader refusals (M73).** `EXTXYZ_VARIABLE_ATOM_COUNT` (v0.1),
  `LAMMPSDUMP_VARIABLE_ATOM_COUNT` (v1.3), and `ASE_TRAJ_VARIABLE_ATOM_COUNT` (v0.3) are gone — those
  trajectories now round-trip and validate per frame. **XDATCAR keeps its refusal**
  (`XDATCAR_VARIABLE_ATOM_COUNT`) because the format writes one element/count header shared by every
  configuration and genuinely cannot represent a varying atom count; the refusal now cites that format
  constraint, not the retired canonical invariant.

## Verified — corpus-scale, and the closed evidence file (M75)

M75 adds no behaviour: it proves the M72–M74 work correct at corpus scale and **closes the refusal
"evidence file"** the ladder kept open since v1.3 — every "this trajectory is real and we cannot
represent it, here is why" is now demonstrated as either convertible or still-refused-with-a-reason, as
committed test assets rather than deleted notes.

**Refusal retirement** — every reader refusal M73 retired, where first recorded, and where its
now-reads-through is demonstrated:

| Refusal code | First recorded | Now demonstrated by |
|---|---|---|
| `EXTXYZ_VARIABLE_ATOM_COUNT` | v0.1 | evidence-closure: a 1→2-atom extXYZ trajectory |
| `ASE_TRAJ_VARIABLE_ATOM_COUNT` | v0.3 | M73 `tests/parsers/test_ase_traj.py` (variable-N `.traj`) |
| `LAMMPSDUMP_VARIABLE_ATOM_COUNT` | v1.3 | evidence-closure: the deposition wild dump |
| `ASEDB_MULTIPLE_ROWS` | v0.3 | evidence-closure: a multi-row ASE `.db` read whole |

**Evidence closure** — the refusal outcomes, each a committed asset in `tests/test_evidence_closure.py`:

| Trajectory class | Source asset | Outcome |
|---|---|---|
| grand-canonical (2→3→4 atoms) | H5MD `gcmc-variable-n-3frame` golden | convertible → extXYZ, validates per frame |
| deposition (3→4→4 atoms) | LAMMPS `dump-variable-n-deposition` wild dump | convertible → extXYZ, validates per frame |
| variable-N extXYZ (1→2 atoms) | inline, mirrors `tests/parsers/test_extxyz.py` | convertible → extXYZ, validates per frame |
| multi-row ASE `.db` (H2 then He) | built as `tests/parsers/test_ase_db.py` does | convertible → extXYZ, validates per frame |
| any constant-N target (POSCAR/CONTCAR/XDATCAR/CIF) | any variable-N source | still refused at pre-flight, offering `frame_selection` — **never** padded, masked, or truncated |

A structural companion (`test_no_code_path_pads_masks_or_truncates_n`) asserts the *absence* of any
ghost-atom code path in `src/xtalate/` by construction, so the no-ghost-atoms rule stays a citable
guarantee, not just a behavioural one.

## Migration

A real `1.0.0 → 2.0.0` migration carries stored 1.x objects forward: the single root-level
`custom_per_atom` array is replicated onto every frame (mechanical, because 1.x guaranteed one N for
all frames), recorded with one `operation="migrate"` provenance record. The migration registry chain
is now `0.1.0 → 1.0.0 → 2.0.0`; older stored objects load through the full chain. See
[docs/MIGRATION.md](../MIGRATION.md) for the four upgrade paths (stored-corpus owner, API client,
library user, plugin author).

Full Changelog: [v1.8.0...v2.0.0](https://github.com/jsong1218/Xtalate/compare/v1.8.0...v2.0.0)

The chained version sync points (`pyproject.toml`, `__version__`, `CITATION.cff`, the README version
badge, and the regenerated `docs/openapi.json`) read `2.0.0`; `frontend/package.json` is deliberately
not a sync point (untouched at `1.0.0` since the v1.0 flip). Tag and publish remain the maintainer's
manual, nightly-green-gated step (D52).
