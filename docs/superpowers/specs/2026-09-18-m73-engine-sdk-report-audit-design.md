# M73 — Engine / SDK / report audit for per-frame-N (design)

> **Status:** design, approved 2026-09-18. Execution milestone **M73** of `IMPLEMENTATION_PLAN_v2.0.md`
> §2 — the audit that follows the M72 gate ("Schema `2.0.0` — Variable-N and H5MD"). This document is the
> slice-level design; the step-by-step plan lives in the companion
> `docs/superpowers/plans/2026-09-18-m73-engine-sdk-report-audit.md`. Scope authority remains
> `MASTER_SPEC.md`; nothing here redefines a report or component beyond what the v2.0 plan already scoped.

## 1. What this milestone is (and is not)

M72 opened the schema so a `CanonicalObject` *can* hold a different atom count per frame, but left every
engine, every validation check, and the streaming/SDK surface still speaking the old constant-N language.
M73 is the systematic pass that makes **every component that ever said "N" answer "which frame's N?"** —
found by audit, not by bug report. It is where the invariant lift stops being a schema fact and becomes a
product fact: variable-N sources parse, convert to variable-N-capable targets, and validate green per
frame; constant-N-only targets refuse at pre-flight instead of a parser refusing at read time.

**Boundaries held (the plan's cut lines, one adjusted):**

- **No binary format here.** H5MD is M74. The only variable-N-capable *targets* available in M73 are the
  text/ASE formats whose exporters already write per-frame (extXYZ, and where trivially per-frame,
  `ase_traj`/`lammps_dump`). That is sufficient for the "converts to a variable-N-capable target, validates
  green" done-criterion.
- **Schema and package versions do not move.** `SCHEMA_VERSION` stays `2.0.0` (M72); product package stays
  `1.8.0` until **M76**, the release milestone. The **SDK** takes a conceptual major here (the `StreamFrame`
  break, §5) but its version-number expression is deferred to M76, consistent with M72's
  schema-bump-without-package-flip pattern.
- **Adjusted from the plan's cut line — the `.db`/assemble upgrades are IN M73** (decision 2026-09-18), not
  deferred to v2.0.1.

## 2. Decisions folded in (2026-09-18)

1. **Implementation mode:** inline (Claude implements each slice, commits, self-reviews) — as M69 and M72.
2. **Reader-refusal retirement scope:** retire **extXYZ + LAMMPS dump** (evidence-backed, named in the v2.0
   plan) **and `ase_traj`** — it natively expresses variable-N and its refusal cites the same lifted Part 2
   §3.2 invariant, so leaving it refused would be an inconsistency a user hits. **XDATCAR stays refused**:
   it is a fixed-composition trajectory format, so `XDATCAR_VARIABLE_ATOM_COUNT` is a *legitimate
   format-capability* refusal, not a canonical-model one, and it remains a `ParseError` (a header that
   restates a different N is a malformed/exotic XDATCAR, not a representable variable-N trajectory).
3. **`.db`/assemble upgrades:** included in M73 (see S5).

## 3. The change surface (grounded in the code)

- **Refusal sites** (all cite the now-lifted "Part 2 §3.2" invariant):
  `src/xtalate/parsers/extxyz.py:288` (materialized) and `:422` (streaming);
  `src/xtalate/parsers/lammps_dump.py:795` (`_VARIABLE_ATOM_COUNT`, defined `:149`);
  `src/xtalate/parsers/ase_traj.py:192`. **Retire these three.**
  `src/xtalate/parsers/xdatcar.py:586` — **keep**, re-worded as a fixed-composition-format constraint.
- **Validation checks:** `src/xtalate/validation/engine.py` — `_check_atom_count` (:304),
  `_check_species` (:327) + its permutation map, `_check_positions_rmsd` (:363), `_check_frame_count`
  (:474), `_check_numeric_fields` (:491); and `validation/streaming.py` for the streamed equivalents.
- **Streaming core:** `PresenceAccumulator`, `convert_stream`/`convert_stream_select`
  (`src/xtalate/conversion/`), `sdk/streaming.py`, and `StreamHeader`/`StreamFrame` in `sdk/plugins.py` /
  `sdk/streaming.py` (the `custom_per_atom` relocation).
- **Capability Matrix:** `sdk/capabilities.py` `FormatCapabilities` (add the axis), every plugin's
  `capabilities()` declaration, `capabilities/registry.py`, `conversion/preflight.py` (pre-flight refusal),
  `recovery/scenarios.py` (`frame_selection` as the offered recovery, line 133 already references the `.db`
  path).
- **`.db`/assemble:** `src/xtalate/parsers/ase_db.py` (`ASEDB_MULTIPLE_ROWS`, `max_frames=1` at :510),
  `src/xtalate/conversion/batch.py:738–765` (assemble whole-object re-parse note).
- **Exporter (target):** `src/xtalate/exporters/extxyz.py` — already iterates `for frame in
  canonical.frames`; verify each frame writes its own count line under variable N.

## 4. The slices

### S1 — Per-frame validation restatements
Restate each object-level check for frames of differing N, each as a spec edit + tests, never a silent
generalization:
- `atom_count` compares per frame.
- `species_preservation` + permutation map operate per frame (a permutation valid for frame 0 need not fit
  frame 3; differing N means differing permutation domains).
- `positions_rmsd` restated for frames of differing N, with per-frame shape guards (a shape mismatch in one
  frame fails that frame's check honestly, not the whole object silently).
- `numeric_field_fidelity` restated for per-frame arrays of differing N.
- `frame_count` restated where per-frame-N changes its meaning.
Tests: variable-N fixtures exercising each check's pass and fail paths.

### S2 — Streaming core per-frame-N audit + identity theorem + the SDK `StreamFrame` break
- Audit `PresenceAccumulator`, `convert_stream`/`convert_stream_select`, and streaming validation for
  per-frame-N correctness.
- **Relocate `custom_per_atom` from `StreamHeader` (object-level) to `StreamFrame`** — the SDK-side mirror
  of M72's schema relocation, the break M72 deferred to "the later SDK major." Both reference-plugin
  canaries (example-format, composition) are the breakage tripwires.
- **Re-prove the M12 identity theorem** ("chunking changes memory, never truth") with new variable-N
  fixtures: the streamed report of a variable-N trajectory is identical to the materialized one.

### S3 — Capability Matrix variable-N axis + padding refusal
- Add `supports_variable_atom_count: bool = False` to `FormatCapabilities`; every format declares it; the
  capability-sync test enforces the declaration matches behaviour.
- Constant-N-only **targets** (POSCAR, XDATCAR, DeePMD systems, single-object `.db`) refuse a variable-N
  source **at pre-flight** through the existing machinery. The offered recovery is the existing
  `frame_selection` scenario (select frames sharing one N — selective-reductive, fully recorded). No new
  scenario is invented for symmetry.
- **Padding/masking is a named, tested refusal.** Alternative rejected: fabricating ghost atoms to satisfy
  a constant-N format is the exact silent-loss class this project exists to refuse (v2.0 plan §5.6). A
  grep-level + test-level guard asserts no code path pads, masks, or truncates N to satisfy a target.

### S4 — Retire reader refusals (extXYZ + LAMMPS dump + ase_traj) + conversion fixtures
- Remove the three canonical-model `*_VARIABLE_ATOM_COUNT` refusals (both the materialized and streaming
  extXYZ paths). **XDATCAR keeps its refusal**, re-worded as a format-capability constraint.
- Confirm the **extXYZ exporter** as the variable-N-capable text target (writes each frame's own count).
- Flip the refusal fixtures to conversion fixtures — the evidence file closes as test assets, not deletions.
- CHANGELOG names each retired refusal and the version that first recorded it.

### S5 — `.db` + assemble upgrades (the included cut-line work)
- A multi-row ASE `.db` with rows of differing N parses as a **single variable-N object** (rows → frames),
  where today the single-file path refuses `ASEDB_MULTIPLE_ROWS`. **Framing decision (D-logged):** `.db`
  rows are independent structures, not a time trajectory, but "rows → frames" is the honest structural
  mapping (as ASE treats `.traj` images) and preserves every row's own N without fabrication. The
  `ASEDB_MULTIPLE_ROWS` refusal is retired for the single-object variable-N read; the batch fan-out (M55)
  remains available where a caller wants per-row files.
- v1.5 mixed-composition assembled extXYZ re-parses as **one variable-N object** → assemble validation
  upgrades from per-contribution-only to **per-contribution + whole-object** (`conversion/batch.py`).

### S6 — SDK-major records + gate + release-surface check
- Records: D-log entries (the retirements, the padding refusal, the `.db` rows→frames framing, the SDK
  `StreamFrame` break, the capability axis); MASTER_SPEC revision notes on Part 2 §3.2 (already lifted),
  §5, Part 5's per-frame check restatements, and Part 3 §3's capability table (variable-N axis); a PROGRESS
  doc updated after every commit.
- SDK-major intent recorded with a per-changed-surface plugin-author migration note; **version-number flip
  deferred to M76**.
- Full gate on **both** Python legs (3.11 Docker + 3.13): `ruff check`, `ruff format --check`, `mypy`,
  `lint-imports`, `pytest` **including the plugin test paths** (`plugins/example-format/tests`,
  `plugins/xtalate-analysis-composition/tests` — the M72 CI-caught lesson).
- **e2e check:** the capability axis surfaces in the generated formats explorer and the pre-flight refusal
  in the recovery flow. If `frontend/`/`backend/` output changes, run the Playwright suite through compose
  **on this branch** before the touching commit. If neither changes, no e2e is owed (record the reason).

## 5. SemVer / SDK posture

- **Schema:** `2.0.0`, unchanged from M72.
- **SDK:** the `StreamFrame.custom_per_atom` relocation is a breaking interface change for streaming
  parsers/exporters. It is the SDK's major, bundled into this one migration event (the "one major, bundled"
  standing rule). Both reference-plugin canaries prove the break is caught; the plugin-author migration note
  documents the moved surface. The SDK version *number* flips at M76 with the package.
- **`/v1` API:** additive at most (M72's report-shape audit found reports survive the major untouched;
  M73's capability-axis field is an additive read-surface addition). No breaking API change.

## 6. Done means

- The variable-N identity theorem holds (streamed report == materialized report on a variable-N fixture).
- A grand-canonical LAMMPS dump and a variable-N extXYZ parse, convert to a variable-N-capable target
  (extXYZ), and validate green per frame; the same source asked for POSCAR refuses at pre-flight with
  `frame_selection` offered.
- Padding is refused, in tests, before H5MD exists to tempt it.
- Both reference-plugin canaries green against the audited SDK.
- Multi-row `.db` and the v1.5 assembled extXYZ re-parse as variable-N objects and whole-object-validate.
- Full gate green on both Python legs (plugin paths included); records complete; freeze held (schema
  `2.0.0`, package `1.8.0`).

## 7. Explicitly out of scope

- H5MD (M74) — no binary container in M73.
- Any package/SDK version-number flip (M76).
- The XDATCAR / POSCAR / DeePMD variable-N *emission* — those formats cannot express variable N; they
  refuse, correctly.
- Corpus-scale nightly widening and property-test generalization over variable-N (M75).
