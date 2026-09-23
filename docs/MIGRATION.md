# Migration guide

This guide covers upgrading Xtalate across a **major** version — the release where the canonical
schema's on-the-wire shape changes and stored objects are carried forward by a real, recorded
migration. Minor and patch releases never need a guide: within a major series every public surface
(the schema, the report schemas, the plugin SDK, the `/v1` REST surface, the documented CLI) evolves
**additively only**, so an upgrade inside `2.x` — like every upgrade inside `1.x` was — is a
`pip install -U` and nothing else.

There has been exactly one major migration so far. It is the only section below.

---

## 1.x → 2.0 — variable atom count per frame

**Package `1.x` → `2.0.0`. Canonical schema `1.0.0` → `2.0.0`.**

Xtalate 2.0 lifts the one invariant the canonical model reserved from the start: every frame of a
trajectory had to share a single atom count *N*. It no longer does — each frame carries its own atom
count, so grand-canonical, deposition, reactive, and mixed-composition trajectories (the classes
earlier versions *measurably refused*, always with a reason and never by truncating or padding) are
now first-class. H5MD, the standardized HDF5 trajectory layout, arrives as the first binary container
that expresses a varying particle number natively.

Because the serialized object's shape changed — one per-atom array container moved from the object
root onto each frame — this is a **major** version under the project's SemVer promise, and stored
objects written by any earlier release are migrated forward by a recorded step.

### For most users: nothing changes

- **Constant-N work is byte-identical.** A trajectory whose frames all share one atom count converts,
  reports, and validates exactly as it did in `1.x` — a constant N is a special case of a per-frame N,
  not a mode. If every file you convert has a fixed composition, upgrading changes none of your output.
- **The `/v1` REST surface, the report schemas, the CLI, and `vocabulary.json` are unchanged.** The
  2.0 audit (milestone M72) verified that reports are statements *about* conversions, not about array
  layout, so they survived the major untouched. In particular the report/capability/`vocabulary.json`
  identifier for the relocated category is still the opaque string `user_metadata.custom_per_atom` — an
  API client that reads reports sees no new or renamed fields.
- **Stored objects migrate on load.** Anything Xtalate reads that was written at schema `0.1.0` or
  `1.0.0` is carried forward through the migration chain (`0.1.0 → 1.0.0 → 2.0.0`) automatically, with
  one `operation="migrate"` provenance record appended per step. You do not run a tool; loading is the
  migration.

If you are a CLI user or an API client converting fixed-N files, you are done — `pip install -U
xtalate` (or pull the new image) and continue.

### What changed, and why exactly one major

The single breaking change is a **relocation**: a per-atom custom array's first dimension is a
*frame's* atom count, which is no longer an object-level quantity, so the container moved from the
object root onto the frame it describes.

- **`1.x`:** `object.user_metadata.custom_per_atom` — one set of per-atom columns for the whole object.
- **`2.0`:** `frame.custom_per_atom` — each frame carries the per-atom columns sized to its own N.

`user_metadata.custom_per_frame` (first dimension = frame count) and `user_metadata.custom_global` are
**unchanged** and stay on the object root. Only the per-atom container moved.

Everything breaking about the `1.x` → `2.0` transition is *this one relocation*. The release bundled a
full sweep of the decision log for anything else that had been deferred as "breaking — next major"
since `1.0`; no other item came due, so 2.0 carries exactly one break. Bundling the era's one breaking
change into a single version is deliberate: with SemVer frozen at `1.0`, downstream migration cost is a
function of how many majors exist, not how large each one is, so the honest and cheapest path is one
well-documented major rather than several small ones.

### By audience

**Stored-corpus owner** — you have `CanonicalObject` JSON on disk or in a database written by an
earlier Xtalate.

- You need to do **nothing** to read them: every load runs the migration chain and returns a current
  `2.0.0` object, stamping one `migrate` provenance record. The relocation is mechanical — because
  `1.x` guaranteed one N for all frames, the single root-level `custom_per_atom` array is replicated
  onto every frame with no interpretation.
- If you want to migrate at rest (rewrite the stored JSON forward once, rather than on every load),
  load each object and re-serialize it; the loaded object is already `2.0.0`. The migration is
  pure JSON-to-JSON and idempotent — an already-`2.0.0` object migrates to itself with no `migrate`
  record added.
- The release's restore drill exercises exactly this: a `0.1.0`-era object restored into a database
  loads through the full `0.1.0 → 2.0.0` chain and validates.

**API client** — you call the `/v1` REST surface.

- **No change is required.** The `/v1` surface is unchanged, and the report bodies embed the same
  models with the same field names. Responses now carry `schema_version: "2.0.0"`.
- The **only** thing to check: if your client hard-coded an equality test on `schema_version` (e.g.
  `assert schema_version == "1.0.0"`), relax it — the version moved on its own axis, as documented. If
  you never inspected `schema_version`, there is nothing to do.

**Library user** — you construct or read `CanonicalObject`s in Python.

- Read per-atom custom columns from **`frame.custom_per_atom`**, not
  `object.user_metadata.custom_per_atom` (the latter no longer exists).
- When you build an object, put per-atom columns on each `Frame`; each frame validates its own
  `custom_per_atom` arrays against its own atom count.
- Objects you load are already migrated — you only touch the new location for objects you build
  yourself.

**Plugin author** — you ship a parser, exporter, or analysis plugin against the SDK.

- **Batch (non-streaming) parsers/exporters:** if you read or wrote per-atom custom columns, they now
  live on the frame (`frame.custom_per_atom`) — the same relocation as for any library user.
- **Streaming parsers/exporters:** `StreamHeader.custom_per_atom` is **removed**; each `StreamFrame`
  carries its own per-atom columns on the frame it wraps. The exact before/after code, for both the
  parse and the export side, is in
  [`docs/DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) — see *"Migrating a streaming plugin to the 2.0
  SDK: per-atom columns move to the frame."* Both first-party reference-plugin canaries (the format
  plugin and the analysis plugin) already conform, so they double as worked examples.
- **Analysis plugins** need no change from this relocation — analysis reads the object and annotates
  its own `user_metadata` namespace, which did not move.

### The new capability, concretely

A trajectory whose atom count changes frame to frame now **reads, converts, and validates per frame**:

- A grand-canonical or deposition **LAMMPS dump**, a variable-N **extended XYZ** trajectory, a
  multi-row **ASE `.db`**, and a variable-N **H5MD** file all parse into one `CanonicalObject` whose
  frames differ in N, and round-trip to any variable-N-capable target (extXYZ, ASE `.traj`, LAMMPS
  dump, ASE `.db`, H5MD), validating frame by frame.
- The refusals earlier versions raised for this data (`EXTXYZ_VARIABLE_ATOM_COUNT` from v0.1,
  `ASE_TRAJ_VARIABLE_ATOM_COUNT` from v0.3, `LAMMPSDUMP_VARIABLE_ATOM_COUNT` from v1.3, and the
  single-file `ASEDB_MULTIPLE_ROWS` refusal) are **retired** — each is now a demonstrated,
  round-tripping read.

The honest boundary is unchanged in spirit: a target format that genuinely cannot express a varying
atom count still **refuses**, and offers the same recovery it always did.

- **Constant-N-only targets — POSCAR, CONTCAR, XDATCAR, CIF — refuse a variable-N source at
  pre-flight**, before any bytes are written, and offer the existing `frame_selection` recovery: pick
  one frame (a single fixed-N structure) or split per frame.
- **No ghost atoms, ever.** Padding, masking, or truncating atoms to force a source into a constant-N
  target is a named non-option — fabricating atoms to satisfy a format is exactly the silent loss this
  project exists to refuse. The choice is a real conversion, an honest refusal, or an explicit
  `frame_selection` — nothing in between.

### If something looks wrong

- A `1.x` object that fails to load: check its `schema_version` — the chain migrates `0.1.0` and
  `1.0.0`; a version outside the chain (a hand-edited or third-party number) is refused with a message
  naming the missing step, never guessed.
- A conversion to POSCAR/CONTCAR/XDATCAR/CIF that used to work now refusing: the source is variable-N;
  choose a frame via `frame_selection`, or pick a variable-N-capable target.
- A plugin that stopped compiling against the 2.0 SDK: it read `StreamHeader.custom_per_atom` — see the
  streaming-plugin note in the DEVELOPER_GUIDE linked above.
