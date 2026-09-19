# M73 — Engine / SDK / report audit for per-frame-N — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every engine, validation check, streaming/SDK surface, and capability declaration answer "which frame's N?" so variable-N sources parse, convert to variable-N-capable targets, and validate green per frame — while constant-N-only targets refuse at pre-flight, never by padding.

**Architecture:** M72 lifted the constant-N schema invariant; M73 is the systematic downstream audit. Most validation checks are already per-frame (they iterate `for i in range(n)`); the real work is (a) the object-level permutation-map assumption, (b) relocating `custom_per_atom` from `StreamHeader` to per-frame `StreamFrame` (the SDK major), (c) a new Capability-Matrix variable-N axis driving a pre-flight refusal with `frame_selection` recovery, (d) retiring three canonical-model reader refusals, and (e) the `.db`/assemble variable-N upgrades. No binary format (H5MD is M74).

**Tech Stack:** Python 3.11/3.13, pydantic v2, numpy, ASE; pytest; ruff + mypy --strict + import-linter; Docker for the 3.11 leg + e2e.

## Global Constraints

- **Schema stays `2.0.0`** (`SCHEMA_VERSION`, set in M72). **No package version flip** — package stays `1.8.0` until M76. Copy these values verbatim; do not change either.
- **SDK takes its major here conceptually** (the `StreamFrame` break) but the version *number* flips at M76.
- **No ghost atoms, ever.** No code path pads, masks, or truncates N to satisfy a constant-N target. The only responses to a variable-N-vs-constant-N-target mismatch are refusal or the existing `frame_selection` recovery.
- **XDATCAR keeps its `XDATCAR_VARIABLE_ATOM_COUNT` refusal** — fixed-composition format, legitimate constraint. Only extXYZ, LAMMPS dump, and ase_traj refusals retire.
- **Both reference-plugin canaries** (`plugins/example-format`, `plugins/xtalate-analysis-composition`) must stay green — they are the SDK-break tripwires.
- **No AI attribution** in commits (git author is the human maintainer). Never `--no-verify`.
- **Lint gate order** (run all locally from `.venv`, then the 3.11 leg in Docker): `ruff check .`, `ruff format --check .`, `mypy`, `lint-imports`, then install both plugins and `pytest tests plugins/example-format/tests plugins/xtalate-analysis-composition/tests` — **the plugin test paths are not collected by bare `pytest`** (M72 CI-caught lesson).
- **Commit message prefix:** `v2.0 M73: <subject>`.
- **Update `docs/private/PROGRESS_v2.0_M73.md` after every commit** (gitignored cross-slice memory; git wins on disagreement).

---

## Task 0: Branch + PROGRESS doc (setup)

**Files:**
- Create: `docs/private/PROGRESS_v2.0_M73.md`

Branch `m73-engine-sdk-report-audit` already exists off the M72 tip (`1b3bed4`) with the design spec committed (`1acaa59`).

- [ ] **Step 1:** Create `docs/private/PROGRESS_v2.0_M73.md` from the M72 progress doc's shape (cross-slice-memory header, a slice table S1–S6 all `TODO`, key-invariants section copying the Global Constraints above, an empty running log). It is gitignored — never committed.
- [ ] **Step 2:** Record a baseline gate run (before any change) so a later regression is attributable. Run the full gate; note pass count + coverage in the running log.

---

## Task 1 (S1): Per-frame validation restatements

**Files:**
- Modify: `src/xtalate/validation/engine.py` (`_check_species` :327, `_check_positions_rmsd` :363, `_check_numeric_fields` :491 — the three that take `perm`)
- Test: `tests/validation/test_variable_n_checks.py` (create)

**Interfaces:**
- Consumes: `CanonicalObject` with frames of differing N; `exporter.atom_permutation(expected) -> list[int] | None`.
- Produces: no signature change — the checks keep their names/params; behaviour is made per-frame-N-safe.

**Finding that scopes this task:** `_check_atom_count`, `_check_species`, `_check_positions_rmsd`, `_check_lattice`, `_check_frame_count`, `_check_numeric_fields` already iterate per frame and already guard differing lengths/shapes. The one real defect is the **object-level `perm`**: `_check_species` line 338 does `order = perm if perm is not None else list(range(len(exp)))` then indexes `exp[order[j]]` for `j in range(len(got))`. If `perm` was computed for frame 0's N but frame *i* has a different N, this indexes out of range or compares the wrong atoms. In practice a non-identity `perm` is produced only by species-grouping exporters (POSCAR), which are constant-N-only and will refuse variable-N at pre-flight (Task 3) — so validation never runs them on variable-N. But the code must be correct-by-construction, not correct-by-luck.

- [ ] **Step 1: Write the failing test — species check on differing-N frames with identity perm.**

```python
# tests/validation/test_variable_n_checks.py
import numpy as np
from xtalate.validation.engine import _check_species, _check_positions_rmsd
# build a 2-frame variable-N object: frame 0 = H2O (3), frame 1 = H2O2 (4)
def _obj(frames):  # helper building a CanonicalObject from (symbols, positions) pairs
    ...

def test_species_check_passes_on_variable_n_identity_perm():
    o = _obj([(["O","H","H"], ...), (["O","O","H","H"], ...)])
    res = _check_species(o, o, None)
    assert res.status == "pass"
```

- [ ] **Step 2:** Run it; expect PASS already (identity path is safe). This locks the baseline.

- [ ] **Step 3: Write the failing test — a non-identity perm sized to frame 0 must not corrupt a differing-N later frame.**

```python
def test_species_check_perm_is_frame0_sized_does_not_crash_on_shorter_frame():
    o = _obj([(["O","H","H"], ...), (["O","H"], ...)])   # frame1 shorter
    # perm sized to frame0 (len 3); frame1 has len 2
    res = _check_species(o, o, [0, 2, 1])
    assert res.status in {"pass", "fail"}   # never IndexError
```

- [ ] **Step 4:** Run it; expect FAIL (IndexError) — proving the object-level-perm defect.

- [ ] **Step 5: Fix — apply `perm` only where its length matches the frame's N; otherwise fall back to identity for that frame** (a non-identity perm only legitimately arises for constant-N targets, so a length mismatch means "this frame is not the permutation's domain").

```python
# in _check_species, inside the per-frame loop, replace the `order = ...` line:
order = perm if (perm is not None and len(perm) == len(exp)) else list(range(len(exp)))
```

Apply the same length-guard in `_check_positions_rmsd` (`_permuted(..., perm)` at :376) and `_check_numeric_fields` (`_permuted(e, perm)` at :539) — permute only when `perm` fits that frame's N; else identity. Add a one-line code comment citing this task and Part 5 §2.

- [ ] **Step 6:** Run the new tests + the full validation suite (`pytest tests/validation -v`); expect PASS.

- [ ] **Step 7: Spec restatement.** In `docs/private/MASTER_SPEC.md` Part 5 §2, add a Revision note that `atom_count`, `species_preservation`, `positions_rmsd`, and `numeric_field_fidelity` compare per frame and that the permutation map applies per frame only where its domain matches (identity otherwise). Add the Revision to the Preface log.

- [ ] **Step 8: Commit.**

```bash
git add src/xtalate/validation/engine.py tests/validation/test_variable_n_checks.py docs/private/MASTER_SPEC.md
git commit -m "v2.0 M73: validation checks apply the permutation map per frame under variable N"
```

---

## Task 2 (S2): Streaming per-frame-N audit + `StreamFrame` relocation + identity theorem

**Files:**
- Modify: `src/xtalate/sdk/streaming.py` (remove `StreamHeader.custom_per_atom` :88; drop the distribution block :188-196; `from_object` :103-109)
- Modify: streaming parsers that write `custom_per_atom` to the header — `src/xtalate/parsers/extxyz.py`, `ase_traj.py`, `lammps_dump.py` (write it onto each `StreamFrame.frame` instead)
- Test: `tests/streaming/test_variable_n_identity.py` (create)

**Interfaces:**
- Consumes: `FrameStream(header: StreamHeader, frame_iter: Iterator[StreamFrame])`; `StreamFrame(frame: Frame, per_frame_custom: dict)`.
- Produces: **breaking** — `StreamHeader` no longer has `custom_per_atom`. Streaming parsers must set `custom_per_atom` on each `StreamFrame.frame`. `materialize()` no longer distributes a header column set (each frame is self-describing).

**The SDK major.** M72 kept `StreamHeader.custom_per_atom` object-level and had `materialize()` distribute it (streaming.py :188-196). M73 relocates it: the field leaves the header, and every streaming parser writes per-atom columns onto its `Frame` (which already holds `custom_per_atom` since M72). This is the "later SDK major" M72's D-b deferred here.

- [ ] **Step 1: Write the failing identity-theorem test — streamed == materialized on a variable-N trajectory.**

```python
# tests/streaming/test_variable_n_identity.py
def test_variable_n_streamed_report_equals_materialized(tmp_path):
    # a variable-N extXYZ file (frame0 3 atoms, frame1 4 atoms)
    path = _write_variable_n_extxyz(tmp_path)
    streamed = convert_stream(path, to="extxyz", ...)      # streamed conversion report
    materialized = convert(path, to="extxyz", ...)          # materialized conversion report
    assert streamed.report.model_dump() == materialized.report.model_dump()
```

- [ ] **Step 2:** Run it; expect FAIL — either the extXYZ reader still refuses variable-N (retired in Task 4) OR the header-distribution path corrupts per-frame columns. **Order note:** this test can only go green after Task 4 retires the extXYZ reader refusal; keep it `xfail(reason="extxyz reader refusal retires in Task 4")` until then, then flip.

- [ ] **Step 3: Relocate the field.** Delete `custom_per_atom` from `StreamHeader` (:88) and from `from_object` (:108). Delete the distribution block in `materialize()` (:188-196) and the `_PER_ATOM_ADAPTER` coercion if now unused. Update `from_object` to instead rely on each `StreamFrame.frame` carrying its own `custom_per_atom` (already true for a materialized object's frames).

- [ ] **Step 4: Update each streaming parser** (`extxyz._stream_frame`, `ase_traj._stream_frame`, `lammps_dump`): ensure the `Frame` yielded in each `StreamFrame` carries that frame's own `custom_per_atom` (grep each for how it currently populates the header vs the frame; move to the frame). Run `mypy` — the removed attribute surfaces every stale reference.

- [ ] **Step 5:** Run the streaming suite + both plugin canaries (`pytest tests/streaming plugins/example-format/tests plugins/xtalate-analysis-composition/tests -v`); expect PASS on constant-N. Fix any canary breakage by following the same per-frame relocation in the plugin (record the plugin-author migration note in Task 6).

- [ ] **Step 6:** After Task 4 retires the extXYZ refusal, remove the `xfail` from Step 1's test; expect PASS.

- [ ] **Step 7: Spec restatement.** MASTER_SPEC Part 2 §3.10 / the streaming section: `StreamHeader` holds only frame-invariant object metadata; per-atom columns ride each `StreamFrame.frame`. Preface Revision note. This is the SDK major surface (recorded fully in Task 6).

- [ ] **Step 8: Commit.**

```bash
git add src/xtalate/sdk/streaming.py src/xtalate/parsers/extxyz.py src/xtalate/parsers/ase_traj.py src/xtalate/parsers/lammps_dump.py tests/streaming/test_variable_n_identity.py docs/private/MASTER_SPEC.md
git commit -m "v2.0 M73: relocate custom_per_atom from StreamHeader to StreamFrame (SDK major); re-prove the identity theorem under variable N"
```

---

## Task 3 (S3): Capability Matrix variable-N axis + pre-flight refusal + padding guard

**Files:**
- Modify: `src/xtalate/sdk/capabilities.py` (add `supports_variable_atom_count: bool = False` to `FormatCapabilities`)
- Modify: every exporter's `capabilities()` — declare the axis (extXYZ/ase_traj/lammps_dump/ase_db-as-source True where the format can express varying N; POSCAR/XDATCAR/deepmd_npy/qe_pw_in/cif/xyz per truth)
- Modify: `src/xtalate/conversion/preflight.py` (new refusal trigger, mirroring the `holds_image_flags`/`requires_units_style` pattern ~:373/:479)
- Test: `tests/capabilities/test_variable_n_axis.py`, `tests/conversion/test_variable_n_preflight.py` (create)

**Interfaces:**
- Consumes: `FormatCapabilities.supports_variable_atom_count: bool`; `presence`/`CanonicalObject.frames`; the existing `frame_selection` `UnresolvedScenario`.
- Produces: a pre-flight refusal (`UnresolvedScenario` offering `frame_selection`) when a variable-N source targets a `supports_variable_atom_count=False` exporter.

- [ ] **Step 1: Write the failing capability-axis test.**

```python
def test_extxyz_declares_variable_n_capable():
    caps = ExtxyzExporter().capabilities()
    assert caps.supports_variable_atom_count is True

def test_poscar_declares_constant_n_only():
    assert PoscarExporter().capabilities().supports_variable_atom_count is False
```

- [ ] **Step 2:** Run; expect FAIL (field does not exist).

- [ ] **Step 3:** Add `supports_variable_atom_count: bool = False` to `FormatCapabilities` (near `holds_image_flags` :95) with a docstring. Declare `True` in extXYZ, ase_traj, lammps_dump, ase_db exporter `capabilities()`; leave the constant-N formats at the `False` default.

- [ ] **Step 4:** Run Step 1's tests; expect PASS. Update the capability-sync test (the one asserting each declaration matches behaviour) to cover the new axis.

- [ ] **Step 5: Write the failing pre-flight refusal test.**

```python
def test_variable_n_source_to_poscar_refuses_at_preflight_with_frame_selection():
    o = _variable_n_object()   # frames of differing N
    result = engine.convert(o_bytes, source="extxyz", target="poscar", ...)
    assert result.report.status == "refused"
    assert any(s.scenario == "frame_selection" for s in result.report.unresolved)

def test_no_ghost_atoms_padding_path_exists():
    # grep-style guard: assert the refusal, never a padded object
    ...
```

- [ ] **Step 6:** Run; expect FAIL (POSCAR currently either errors differently or pads/truncates).

- [ ] **Step 7:** In `preflight.py`, add a trigger: if the source object has frames of differing N (`len({len(f.atoms.symbols) for f in frames}) > 1`) and `not caps.supports_variable_atom_count`, emit the `frame_selection` `UnresolvedScenario` (reuse `available_options`), with a `FORMAT_LOSSY_NOTE`/capability Warning naming the constant-N constraint. Read the flag directly from `caps`, following the `requires_units_style` arm (:479).

- [ ] **Step 8:** Run Step 5's tests + the full conversion/preflight suite; expect PASS. Add a test asserting a **constant-N** source to POSCAR still Preserved (no false refusal).

- [ ] **Step 9: Spec restatement.** MASTER_SPEC Part 3 §4 capability table gains the variable-N axis column; Part 4 §3.3 notes `frame_selection` as the variable-N-vs-constant-N-target recovery; the padding refusal is stated as a named non-option. Preface Revision.

- [ ] **Step 10: Commit.**

```bash
git add src/xtalate/sdk/capabilities.py src/xtalate/exporters/*.py src/xtalate/conversion/preflight.py tests/capabilities/test_variable_n_axis.py tests/conversion/test_variable_n_preflight.py docs/private/MASTER_SPEC.md
git commit -m "v2.0 M73: Capability Matrix variable-N axis; constant-N targets refuse variable-N at pre-flight with frame_selection"
```

---

## Task 4 (S4): Retire the extXYZ + LAMMPS + ase_traj reader refusals + conversion fixtures

**Files:**
- Modify: `src/xtalate/parsers/extxyz.py` (:288 materialized, :422 streaming), `lammps_dump.py` (:795), `ase_traj.py` (:192)
- Modify: `src/xtalate/exporters/extxyz.py` (confirm per-frame count line under variable N)
- Modify: refusal fixtures → conversion fixtures; `CHANGELOG.md`
- Test: `tests/parsers/test_extxyz.py`, `test_lammps_dump.py`, `test_ase_traj.py`; a round-trip test

**Interfaces:**
- Consumes: the now-lifted schema (each `Frame` its own N).
- Produces: variable-N `CanonicalObject`s from these three readers; a variable-N extXYZ export.

- [ ] **Step 1: Write the failing parse test — a variable-N extXYZ now parses.**

```python
def test_extxyz_parses_variable_n_trajectory(tmp_path):
    p = _write_extxyz([["O","H","H"], ["O","O","H","H"]], ...)  # 3 then 4 atoms
    obj = ExtxyzParser().parse(open(p,"rb")).canonical
    assert [len(f.atoms.symbols) for f in obj.frames] == [3, 4]
```

- [ ] **Step 2:** Run; expect FAIL (raises `EXTXYZ_VARIABLE_ATOM_COUNT`).

- [ ] **Step 3:** Remove the materialized refusal (extxyz.py :283-292 `n_atoms` divergence block) and the streaming refusal (:421-428). The parser already builds each frame from its own `atoms`; drop the `n_atoms` equality gate. Repeat for `lammps_dump.py:795` and `ase_traj.py:192`. **Leave `xdatcar.py:586` untouched** (fixed-composition — re-word its comment to cite the format constraint, not the retired invariant).

- [ ] **Step 4:** Run Step 1's test + the same for LAMMPS dump (a grand-canonical/deposition fixture) and ase_traj; expect PASS.

- [ ] **Step 5: Write the failing round-trip test — variable-N extXYZ → canonical → extXYZ, validate green per frame.**

```python
def test_variable_n_extxyz_roundtrips_and_validates_per_frame(tmp_path):
    obj = ExtxyzParser().parse(...).canonical
    out = ExtxyzExporter().export(obj)
    report = validate(obj, out, target="extxyz")
    assert report.overall == "pass"
    assert report.check("atom_count").status == "pass"
```

- [ ] **Step 6:** Run; if the exporter mis-writes a shared count, FAIL. Fix `exporters/extxyz.py` so each frame writes its own `len(frame.atoms.symbols)` count line (audit the `for frame in canonical.frames` loops at :75/:94/:289). Run; expect PASS.

- [ ] **Step 7: Flip refusal fixtures to conversion fixtures.** Find the fixtures asserting `EXTXYZ_VARIABLE_ATOM_COUNT` / `LAMMPSDUMP_VARIABLE_ATOM_COUNT` / `ASE_TRAJ_VARIABLE_ATOM_COUNT` refusals (grep `tests/`), convert each to a successful-conversion fixture (keep the file as a test asset — evidence closes, not deleted). Update any test asserting the refusal to assert the conversion.

- [ ] **Step 8: CHANGELOG.** Under `[Unreleased]`, add a "Retired refusals" subsection naming each code and the version that first recorded it (`EXTXYZ_VARIABLE_ATOM_COUNT` — v0.1; LAMMPS constant-N — v1.3; `ASE_TRAJ_VARIABLE_ATOM_COUNT` — the version ase_traj landed, v0.3).

- [ ] **Step 9:** Run the full parser + roundtrip + streaming suites (including Task 2's now-un-`xfail`ed identity test); expect PASS.

- [ ] **Step 10: Commit.**

```bash
git add src/xtalate/parsers/extxyz.py src/xtalate/parsers/lammps_dump.py src/xtalate/parsers/ase_traj.py src/xtalate/parsers/xdatcar.py src/xtalate/exporters/extxyz.py tests/ CHANGELOG.md docs/private/MASTER_SPEC.md
git commit -m "v2.0 M73: retire the extXYZ/LAMMPS/ase_traj constant-N reader refusals; variable-N round-trips through extXYZ"
```

---

## Task 5 (S5): `.db` rows-as-variable-N-object + assemble whole-object upgrade

**Files:**
- Modify: `src/xtalate/parsers/ase_db.py` (`ASEDB_MULTIPLE_ROWS` :154/:193/:209/:225; `max_frames=1` :510)
- Modify: `src/xtalate/conversion/batch.py` (assemble whole-object re-parse note :738-765)
- Test: `tests/parsers/test_ase_db.py`, `tests/conversion/test_assemble_variable_n.py` (create/extend)

**Interfaces:**
- Consumes: the retired variable-N readers (Task 4); variable-N `CanonicalObject`.
- Produces: a multi-row `.db` parsed as one variable-N object (rows → frames); assemble validation gains a whole-object pass.

**D-logged framing:** `.db` rows are independent structures, not a time trajectory, but "rows → frames" is the honest structural mapping (as ASE treats `.traj` images) and preserves each row's own N without fabrication. The `ASEDB_MULTIPLE_ROWS` single-file refusal is retired for the variable-N read; the batch fan-out (M55) stays for per-row files.

- [ ] **Step 1: Write the failing test — a multi-row `.db` with differing-N rows parses as one variable-N object.**

```python
def test_multirow_db_parses_as_single_variable_n_object(tmp_path):
    p = _write_db([atoms_3, atoms_4])   # two rows, differing N
    obj = AseDbParser().parse(open(p,"rb")).canonical
    assert [len(f.atoms.symbols) for f in obj.frames] == [3, 4]
```

- [ ] **Step 2:** Run; expect FAIL (`ASEDB_MULTIPLE_ROWS`).

- [ ] **Step 3:** In `ase_db.py`, change the single-file path: instead of refusing a multi-row db, read each row into a frame (raise `max_frames` from 1 to the reader's cap; keep `FrameLimitExceeded` honest). Keep the refusal only where genuinely ambiguous (document which, if any). Run; expect PASS.

- [ ] **Step 4: Write the failing assemble test — the v1.5 mixed-composition assembled extXYZ re-parses as one variable-N object and whole-object-validates.**

```python
def test_mixed_composition_assemble_whole_object_validates(tmp_path):
    # assemble N structures of differing composition into one extXYZ, then re-parse whole
    result = assemble([water, methane, ...], to="extxyz", ...)
    assert result.whole_object_validation.overall == "pass"
```

- [ ] **Step 5:** Run; expect FAIL (assemble currently does per-contribution-only; whole-object re-parse previously refused `EXTXYZ_VARIABLE_ATOM_COUNT`).

- [ ] **Step 6:** In `batch.py` (:738-765), now that whole-file re-parse succeeds, add the whole-object validation pass beside the per-contribution one; drop the special-case note that a variable-N assembled file cannot re-parse. Run; expect PASS.

- [ ] **Step 7: Spec + CHANGELOG.** MASTER_SPEC: `.db` rows→frames mapping and the assemble whole-object upgrade. CHANGELOG `[Unreleased]`: both upgrades. Preface Revision.

- [ ] **Step 8: Commit.**

```bash
git add src/xtalate/parsers/ase_db.py src/xtalate/conversion/batch.py tests/ CHANGELOG.md docs/private/MASTER_SPEC.md
git commit -m "v2.0 M73: multi-row .db parses as one variable-N object; assemble gains whole-object validation"
```

---

## Task 6 (S6): Records, SDK-major migration note, full gate + release-surface check

**Files:**
- Modify: `docs/private/DECISIONS.md` (new D-entries), `docs/private/MASTER_SPEC.md` (Preface Revision consolidation), `docs/DEVELOPER_GUIDE.md` (plugin-author migration note for the `StreamFrame` break)
- Modify: `docs/private/PROGRESS_v2.0_M73.md` (finalize)

**Interfaces:** none (records + verification).

- [ ] **Step 1: D-log entries** — one per decision, each with a rejected alternative: the three retirements (evidence-backed) + XDATCAR-stays; the padding refusal (reject: pad/mask ghost atoms); the `.db` rows→frames framing (reject: keep refusing / keep batch-only); the `StreamFrame` `custom_per_atom` relocation = SDK major (reject: split the break across two majors); the Capability-Matrix variable-N axis (reject: infer per-object at write time). Number them after the M72 D-block (D274/D275 → D276…).

- [ ] **Step 2: Plugin-author migration note** in `docs/DEVELOPER_GUIDE.md`: streaming parsers/exporters must write `custom_per_atom` onto each `StreamFrame.frame`, not the header; `StreamHeader.custom_per_atom` is removed. Show the before/after. Confirm both reference plugins already conform (from Task 2).

- [ ] **Step 3: PROGRESS finalize** — mark S1–S6 DONE with commit hashes and gate results.

- [ ] **Step 4: Full gate, 3.13 leg (local `.venv`).**

Run: `ruff check . && ruff format --check . && mypy && lint-imports && pip install --no-deps ./plugins/example-format ./plugins/xtalate-analysis-composition && pytest tests plugins/example-format/tests plugins/xtalate-analysis-composition/tests`
Expected: all green; note pass count + coverage (≥ prior floor ~92%).

- [ ] **Step 5: Full gate, 3.11 leg (Docker).** Run the same inside the 3.11 image (the numpy-stub split trips `mypy no-any-return` only on 3.11 — memory: lint-3-11-before-ending-milestone). Expected: green on both `mypy` and `pytest`.

- [ ] **Step 6: Release-surface / e2e check.** The capability axis surfaces in the generated formats explorer (`/v1/capabilities` → frontend) and the pre-flight refusal in the recovery flow. Check `git diff --stat main -- frontend/ backend/` and the generated `docs/openapi.json`/`docs/vocabulary.json`. If `frontend/`/`backend/` output changed, run the Playwright suite through compose **on this branch** (`XTALATE_MAX_UPLOAD_BYTES=1048576 docker compose up -d --build --wait`; e2e against `E2E_BASE_URL=http://localhost:3000`; `docker compose down -v`). If neither changed, record "no frontend/backend change → no e2e owed" in PROGRESS.

- [ ] **Step 7: Commit records.**

```bash
git add docs/DEVELOPER_GUIDE.md
git commit -m "v2.0 M73: plugin-author migration note for the StreamFrame per-atom relocation"
```

(D-log, MASTER_SPEC private edits, and PROGRESS are gitignored — no commit; verify with `git status`.)

---

## Self-review notes

- **Spec coverage:** S1→Task 1, S2→Task 2, S3→Task 3, S4→Task 4, S5→Task 5, S6→Task 6. Every "Done means" bullet from the spec maps to a task (identity theorem→T2; per-frame validation→T1; padding refused→T3; canaries green→T2/T6; `.db`+assemble→T5; gate/freeze→T6).
- **Ordering dependency:** T2's identity test is `xfail` until T4 retires the extXYZ reader refusal, then flipped in T2/T4. Called out explicitly in both tasks.
- **Type consistency:** the new capability field name `supports_variable_atom_count` is used identically in T3's model, exporters, and preflight. `perm` length-guard is applied in all three perm-taking checks in T1.
- **No package/schema version change** appears in any task — verified against Global Constraints.
