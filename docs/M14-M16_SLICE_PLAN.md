# v0.3 Tail — M14 / M15 / M16 Slice Plan (execution aid)

> **Purpose.** This is the user-provided slice plan for the v0.3 tail (M14 ASE `.traj`,
> M15 benchmark seed + nightly matrix, M16 entry-point discovery + release), cutting each
> milestone into standalone importable sessions. It is an *execution aid* layered on top of
> `docs/IMPLEMENTATION_PLAN_v0.3.md` (the authoritative plan) — where they differ, the
> implementation plan and `docs/MASTER_SPEC.md` win. Saved here so it is not lost when the
> working session's context is compacted.
>
> ## Progress tracker
> - **M14A — DONE** (branch `m14-ase-traj`, commit `39d88a3`): `ase_traj` parser + exporter +
>   capabilities + registration; decisions **D58** (`fixed_atoms` kind + empty-list laundering to
>   `None`) and **D59** (ASE-version in `parser_version`, via optional override on
>   `parse_record`/`build_provenance`) logged. Full lint gate + 921 tests green.
> - **M14B — DONE** (branch `m14-ase-traj`): default-laundering suite + ASE-version canary in
>   `tests/parsers/test_ase_traj.py` (16 tests) — launders absent cell/momenta/masses/charges/
>   magmoms/empty-constraints to `None`, verifies velocity unit conversion, FixAtoms→fixed_atoms,
>   non-FixAtoms carried-with-warning, stress carried (D18), and the canary (installed ASE
>   satisfies the pyproject pin + `ase <ver>` appears in `provenance.history[0].parser_version`).
>   Full lint gate + 937 tests green (91.64% cov).
> - **M14C–E — TODO** (each depends only on 14A; run in any order).
> - **M15A/B — TODO** (independent); **M15C — TODO** (depends on 15A+15B).
> - **M16A — TODO**; **M16B — TODO** (dep 16A); **M16C — TODO** (dep 16A/16B).
>
> Rough order: **M14 (14A → 14B–E) → M15 (15A/15B → 15C) → M16 (16A → 16B → 16C)**; M14 and
> M15 can interleave (M15's nightly matrix is registry-driven and picks up `ase_traj` once M14
> lands).

---

## Shared context (every slice repeats what it needs)

- Repo: `/Users/ailsayilu/Xtalate`. Format id is **`ase_traj`**, extension `.traj`.
- ASE is the only scientific dependency (D7), pinned `ase>=3.29,<4`. Package `__version__ = "0.2.0"`.
- **Absence convention (P3):** `None` = source did not express it; a value (incl. zeros) = it did.
  Parsers never default. ASE manufactures defaults (zero cell, `pbc`, zeroed momenta, Z-derived
  masses, empty constraints list) — laundering those back to `None` is M14's central obligation.
- **Lint gate before every commit** (from `.venv`): `ruff check .`, `ruff format --check .`,
  `mypy`, `lint-imports`, `pytest`. `ruff format --check` fails independently of `ruff check`.
- **P2 layering** (import-linter): `parsers/` and `exporters/` must not import each other; both
  depend only on `schema` + `sdk`. (extXYZ/ase_traj redefine the velocity constant in the exporter
  rather than import it from the parser for exactly this reason.)
- No AI attribution in commits (D10).

---

# M14 (ASE `.traj` parser/exporter) — 5 slices

**Why:** M14 (`docs/IMPLEMENTATION_PLAN_v0.3.md:71-84`) adds the ASE trajectory parser+exporter —
the richest Phase-1 format, whose worked example anchors the spec. **14A is the foundation;
14B–E each depend only on 14A** and are independent of one another. Two are non-cuttable hard
gates: the **default-laundering suite (14B)** and the **executable worked-example (14D)**.

## SLICE 14A — Core parser + exporter + capabilities + registration ✅ DONE
Streaming-first ASE-backed parser/exporter covering full field breadth; capability rows declared;
format registered so `xtalate capabilities ase_traj` works and an in-memory round-trip passes.
Deliverable 1 + registration half of deliverable 5. Settled two design decisions:
1. **Constraint `kind` string** — ASE `FixAtoms` → `Constraint(kind="fixed_atoms", parameters={},
   atom_indices=[…])`, listed in `representable_constraint_kinds`. Exotic ASE constraints carried
   as custom data with a warning (cut line). **(D58)**
2. **ASE-version recording** — folded into `parser_version`
   (`f"ase_traj-parser {__version__} (ase {ase.__version__})"`) + a `parse_notes` entry, via an
   optional `parser_version` override on `parse_record`/`build_provenance`. **(D59)**

Patterns mirrored: streaming-first structure → `parsers/xdatcar.py`
(`parse = materialize(parse_stream(...))`); ASE↔Canonical + laundering → `parsers/extxyz.py`
(zero-cell→None, momenta→velocities via `ase_units.fs`, masses only if declared, `_partition_calc`
splitting calc results into mapped vs carried; stress carried to `custom_per_frame`, **not**
`electronic.stress`, D18). Files: `src/xtalate/parsers/ase_traj.py`,
`src/xtalate/exporters/ase_traj.py`, registered in `builtin_parsers()`/`builtin_exporters()`,
id-set assertion in `tests/parsers/test_builtins_registration.py` (now six ids),
`tests/parsers/test_ase_traj_smoke.py`. **Notes for later slices:** ASE `.traj` also carries
per-atom `initial_charges`/`initial_magmoms` arrays (→ `electronic.charges`/`magnetic_moments`);
an empty ASE constraints list launders to `None` (D58 addendum); `TrajectoryReader` accepts a
`BytesIO` and is lazy/random-access (good for 14E). Sniff: ULM magic `b"- of Ulm"` + `b"ASE-Trajectory"`.

## SLICE 14B — Default-laundering suite + ASE-version canary (HARD GATE)
Depends on 14A. Highest-value parser tests (Part 8 §1.1) applied to ASE's inventions + the
version canary. Deliverables 2 & 3; **non-cuttable exit gate** (`:84`). Mirror
`tests/parsers/test_extxyz.py:40-82` — each test builds a tiny in-memory fixture, parses, asserts
one canonical field is `None`/recorded:
- `test_launder_absent_cell_to_none` — ASE default zero cell → `cell is None`.
- `test_launder_absent_momenta_to_none` — no momenta → `dynamics.velocities is None`.
- `test_launder_absent_masses_to_none` — Z-derived masses → `atoms.masses is None`.
- laundering for `initial_charges`/`initial_magmoms` absent → `electronic.charges/magnetic_moments is None`.
- empty ASE constraints list → `dynamics.constraints is None`; a `FixAtoms` → the modelled list.
- `test_velocities_unit_converted_from_momenta` (mirror extXYZ), and pbc taken verbatim from a real cell.
- **ASE-version canary:** assert the installed ASE satisfies the pin **and** the version chosen in
  14A appears in `provenance.history[0].parser_version` of a parsed object. **New pattern.**
Files: `tests/parsers/test_ase_traj.py` (+ optional `test_ase_traj_version.py`).
Absence anchors to reuse: `tests/schema/test_models.py:50,63-66`; `tests/roundtrip/test_identity.py:96-104`.

## SLICE 14C — Golden cases + identity round-trip + matrix membership
Depends on 14A. Committed golden fixtures (rich all-fields trajectory; minimal molecule;
laundering cases), identity round-trip, automatic two/three-hop matrix membership. Deliverable 5.
Golden layout mirrors `tests/golden/xdatcar/nacl-md-fixed-cell/`: per case
`tests/golden/ase_traj/<case>/` with the `.traj` bytes, `expected.canonical.json`
(`CanonicalObject.model_dump_json()`, hand-verified), and `manifest.yaml`. **Manifest required
keys** (`tests/golden/_governance.py:validate_manifest_schema:159-228`): `case`,
`format_id: ase_traj`, `source_file`, `expected_canonical`, `canonical_schema_version: "0.1.0"`,
`sha256` (64-hex of source bytes), `expected_sha256` (64-hex of the JSON), `origin`
(`kind: synthetic`, non-empty `license` e.g. `Apache-2.0`). Governance also requires **every data
file be claimed by a manifest** and **`tests/golden/ATTRIBUTIONS.md` be byte-identical to the
regenerated aggregate** — regenerate with `python tests/golden/_governance.py`. Test module mirrors
`tests/golden/test_xdatcar_golden.py` (`CASES` + `test_parse_matches_golden` /
`test_streamed_parse_matches_golden` / `test_identity_roundtrip_through_the_streaming_path`, via
`tests/_format_helpers.py:assert_matches_golden`). **Matrix membership (payoff, near-zero edits):**
add one line to `_GOLDEN_DIRS` in `tests/roundtrip/_matrix.py:47-55`
(`"ase_traj": ("ase_traj/<case>", "<fixture>.traj")`) — enrolls `ase_traj` as a two/three-hop
source; it is already a target the moment 14A registered its exporter. `FIXED_PRESETS`
(`_matrix.py:73-76`) already cover the no-cell-trajectory→POSCAR gap. Identity test:
`test_ase_traj_identity` in `tests/roundtrip/test_identity.py` (or inside the golden module).

## SLICE 14D — Executable worked-example reproduction (HARD GATE / milestone exit door)
Depends on 14A (14C helpful). Make the spec's flagship `relax.traj → POSCAR` example *executable*,
reproducing the Part 4 §5 Conversion Report and Part 5 §6 Validation Report shapes end to end.
Deliverable 4; explicit **exit door** (`:126` "don't tag without it"), **non-cuttable**. Command
(already a test constant `_RECOVER` at `tests/cli/test_cli.py:29-34`):
```
xtalate convert relax.traj --to poscar -o POSCAR \
  --recover frame_selection=last \
  --recover missing_lattice=bounding_box,padding_ang=5.0 \
  --report conversion.json --validation-report validation.json
```
Source fixture: a committed generator building `relax.traj` — isolated **3-atom water molecule,
10 frames**, each with symbols/positions + `dynamics.forces` + `electronic.total_energy`, **ASE
default zero cell** (launders to `cell = None`), no velocities/stress/charges/constraints (per
`docs/MASTER_SPEC.md:1876`). Build generator-style like `tests/streaming/_generators.py`
(deterministic/seeded). Expected shapes fully specified in `docs/MASTER_SPEC.md`: **Conversion
Report** at lines **1903–1951** (`stage:"final"`, `status:"completed"`; `preserved`=[symbols,
positions frame 9]; `supplied`=[`cell.lattice_vectors`, `cell.pbc`] both `from_assumption:"A2"`;
`removed`=[positions frames 0–8, forces, total_energy]; assumptions A1=`frame_selection/last/
{frame_index:9}`, A2=`missing_lattice/bounding_box/{padding_ang:5.0,computed_on_frame:9}`;
`warnings`=[`COORDINATE_REPRESENTATION_CHANGED`, `PRECISION_LIMIT`]). **Validation Report** at
**2154–2232** (`status:"passed"`; the nine checks incl. `numeric_field_fidelity(skipped)`;
`tolerance_profile:"default"`). Recovery plumbing exists (`recovery/engine.py` `_RESOLUTION_ORDER`;
CLI `--recover` in `cli/main.py:_parse_recover`) — you are wiring `ase_traj` in, not building it.
Test: end-to-end CLI test (mirror `tests/cli/test_cli.py:71-95,164-188`) that generates
`relax.traj`, runs `xtalate.cli.main.main(argv)` with `_RECOVER`, and diffs the emitted reports
against spec-derived fixtures, normalizing volatile fields (reuse `_norm` pattern from
`tests/streaming/test_streaming_frame_selection.py:47-54`; **also normalize `source.sha256`**).
Done bar: "byte-for-byte against the spec fixtures (modulo timestamps/ids)."

## SLICE 14E — Streaming-memory proof (conditional on ASE lazy reading)
Depends on 14A. Prove memory stays sub-linear in frames through the streaming path (M12 property
extended to `ase_traj`). **Feasibility already confirmed in 14A:** ASE `TrajectoryReader` supports
lazy random access from a `BytesIO`, so implement the streaming generator + memory test. Add
`write_ase_traj_trajectory(path, n_frames, n_atoms, seed=…)` to `tests/streaming/_generators.py`
(mirror `write_xdatcar_trajectory:54-99` — deterministic, frame-by-frame, never committed). The RSS
probe `tests/streaming/_mem_probe.py` is already format-generic (no edits). Add a memory test to
`tests/streaming/test_streaming_memory.py` mirroring
`test_xdatcar_conversion_is_sublinear_in_frames:80-91` (e.g. 2500 frames × 50 atoms,
`_probe("stream", src, out, "ase_traj", "extxyz")`, `_assert_sublinear`, reports byte-identical
between paths). Optionally an `ase_traj → poscar` streaming `frame_selection=last` test. (If lazy
access had failed, the fallback was to document eager parse in `docs/MEMORY_CEILING.md` + a
`DECISIONS.md` note — not needed.)

## After all 5 slices — milestone close
M14 done when: 14B laundering green, 14D worked-example green, 14C identity + matrix membership
green, 14A registered (`xtalate capabilities` lists six: XYZ, extXYZ, POSCAR, CONTCAR, XDATCAR,
ase_traj), 14E resolved. Does **not** cut the v0.3 tag — M15/M16 remain. Any capability-row/spec
drift gets a Revision note in the same PR.

---

# M15 (Benchmark seed + nightly matrix) — 3 slices

**Why:** M15 (`:88-100`) turns performance into a tracked number and moves the O(n²) round-trip
suites to their nightly home. **15A (corpus + harness)** and **15B (PR/nightly split)** are
independent; **15C (nightly workflow + audit + memory-ceiling)** depends on both. Cut line (`:100`):
auto-issue plumbing and artifact-charting polish may be cut — never the memory measurements or the
nightly matrix. Guard 15B's curated `ase_traj→poscar` pair on registry membership so it skips
until M14 lands.

**Shared context:** only one CI workflow today — `.github/workflows/ci.yml` (single `lint-and-test`
job, Python 3.11+3.13, `fail-fast:false`, `pull_request`+`push:[main]`); **no nightly/scheduled
workflow, no `actions/upload-artifact`.** Reuse seeds: `tests/streaming/_generators.py`
(`write_extxyz_trajectory`, `write_xdatcar_trajectory(..., npt=)`, seed 1234) and
`tests/streaming/_mem_probe.py` (subprocess peak-RSS, `_peak_rss_bytes()` normalizes macOS-bytes
vs Linux-KiB). Coverage ratchet in `pyproject.toml` addopts (`--cov-fail-under=91`) — run
benchmark/nightly-scale modules in a separate pytest invocation without the coverage gate.
Standing rules: measured-not-gated for perf (`MASTER_SPEC:2963`); a nightly failure opens/updates a
tracking issue, doesn't block PRs.

## SLICE 15A — Synthetic performance corpus + benchmark harness (measured, not gated)
Deliverables 1 & 2. **Greenfield: no `benchmarks/` or perf harness.** Seed the benchmark table
(`MASTER_SPEC` Part 8 §4, lines 2949–2963): `parse_xdatcar_10k` (10k×100, ≤30s, ≤2GB),
`convert_xdatcar_to_extxyz_10k` (full pipeline incl. validation, ≤90s, ≤2GB),
`convert_extxyz_roundtrip_1k` (1k×1k identity round-trip, ≤60s, ≤3GB), `frame_limit_ceiling`
(100k-frame file, sub-linear memory), `preflight_latency` (pre-flight on parsed 10k-frame object,
≤1s). Reuse generators (call at scale, keep "generated, never committed") and `_mem_probe.py`
RSS+timing (subprocess per benchmark). `frame_limit_ceiling` = reduced-scale sub-linear probe
(mirror `_assert_sublinear:37-66` at ceiling scale). `preflight_latency` drives
`conversion/preflight.py:build_preflight_from_presence:117`. Create `benchmarks/` (or
`tests/benchmark/`): `harness.py` (each benchmark in a subprocess, emits JSON/CSV time+RSS series)
+ a `__main__` so `python -m benchmarks` runs all five. Keep out of the coverage-gated pytest run.
No new deps (stdlib + existing generators; avoid `pytest-benchmark`).

## SLICE 15B — PR/nightly test-matrix split + property-test budget profiles
Part of deliverable 3. **Changes what runs where** (15C adds the workflow). Current state (all on
every PR): `tests/roundtrip/test_two_hop.py:29-38` collects full n×n at import
(`_matrix.two_hop_pairs`); `test_three_hop.py:33-42` already curated (hard-coded pairs);
`test_identity.py` per-format (keep on PR). No marker system / root `conftest.py` / env gating yet.
Property budgets: `tests/property/test_report_completeness_hypothesis.py:41`
`@settings(max_examples=200)`. Curated-subset definition (`MASTER_SPEC` Part 8 §2.4, line 2903):
PR subset = identity for **all** formats + two-hop for a curated high-risk pair list (near-supersets
XYZ↔extXYZ; fractional↔Cartesian e.g. POSCAR↔extXYZ; recovery-exercising **`ase_traj→poscar`**,
membership-guarded). Full n×n runs nightly. Mechanism: root `conftest.py` + register a `nightly`
marker in `pyproject.toml`; add `curated_pr_pairs(registry)` to `tests/roundtrip/_matrix.py`; in
`test_two_hop.py` parametrize the curated list by default, gate the full list behind
`XTALATE_FULL_MATRIX=1`/the `nightly` marker. Property tests:
`settings.register_profile("pr"/"nightly")` via `HYPOTHESIS_PROFILE` (default `pr`). Keep
`test_matrix_enumeration.py` green; drop no pair.

## SLICE 15C — Nightly CI workflow + dependency audit + memory-ceiling finalization
Depends on 15A+15B. Rest of deliverable 3 + deliverable 4. Create `.github/workflows/nightly.yml`
(target shape `MASTER_SPEC` §5 lines 2989–2998, Part 9 §3 line 3057): `on: schedule` (cron) +
`workflow_dispatch`; steps `pip install -e ".[dev]"` → full matrix
(`XTALATE_FULL_MATRIX=1 pytest -m nightly`) → benchmarks (`python -m benchmarks`) with
`actions/upload-artifact` for the time+RSS series (new pattern) → extended properties
(`HYPOTHESIS_PROFILE=nightly pytest tests/property`) → dependency audit (`pip-audit`). The >20%
regression tripwire is **NOT** wired (measured only; activates on v0.5's pinned runner). Auto-issue
-on-failure (`if: failure()` → `gh issue create`/action) is the cut line — degrade to a plain red
scheduled run if fiddly; never cut matrix/benchmarks. Add `pip-audit` to dev extra (nightly-only,
non-blocking). Finalize `docs/MEMORY_CEILING.md` (`:62-66` extXYZ, `:72-76` XDATCAR) with measured
numbers tied to `frame_limit_ceiling`/`convert_xdatcar_to_extxyz_10k` and the 2GB/3GB bounds; keep
the `peak ∝ chunk_size × atoms` model. Done: one green `workflow_dispatch` run, downloadable
benchmark artifacts, PR suite back under ~10min, `MEMORY_CEILING.md` carries real numbers.

---

# M16 (Entry-point plugin discovery + release) — 3 slices

**Why:** M16 (`:104-116`) is v0.3's cut line — additive `importlib.metadata` entry-point discovery
(deferred from v0.1 by design) plus the release. **16A** is the foundation; **16B** (proof plugin)
dep 16A; **16C** (docs + release) dep 16A/16B. Version's cut line lives inside M16 (`:116`):
discovery half (16A+16B + entry-point docs) slips to v0.4 before anything in M12–M15 is cut; the
**release half (16C item 4) is never cut** — v0.3 tags when M15 is green regardless, discovery
honestly stated as deferred. **Watch-outs:** confirm `v0.2.0` was actually tagged/published before
tagging `v0.3.0`; cross-check `builtin_parsers()` at release time and state the true format count
(the "six formats" README line is premature until M14 lands).

**Shared context:** `requires-python=">=3.11"` → use `entry_points(group="xtalate.parsers")`.
Registry seam: `src/xtalate/registry.py:21-28` `default_registry()` registers `builtin_parsers()`
then `builtin_exporters()`; entry-point discovery is a **third pass after** those loops (first-party
ids first; a colliding third-party `format_id` hits the duplicate guard `ValueError` in
`capabilities/registry.py:99`). Builtin lists stay explicit — discovery is additive. Group names
(`MASTER_SPEC:1570`): `xtalate.parsers`, `xtalate.exporters`. Validation is free: entry-point
plugins register through the same `register_parser`/`register_exporter` →
`expand_capability_path` → `InvalidCapabilityDeclaration`. Publishing is manual (D52): `git tag` +
`python -m build` + `twine upload` + GitHub release. Version is static in three files:
`pyproject.toml:7`, `src/xtalate/__init__.py:13`, `CITATION.cff:13-14`.

## SLICE 16A — Entry-point discovery mechanism + declaration validation
Deliverable 1. **Greenfield.** Add `_register_from_entry_points(registry)` to `registry.py`, called
after the two builtin loops; iterate `entry_points(group="xtalate.parsers")` /
`"xtalate.exporters"`, `ep.load()`, instantiate, `register_*` (each gets duplicate-detection +
capability validation free). **Design decision (record in DECISIONS.md):** "done means" a
bad-declaration plugin fails loudly at load (`:115`), rejected with a readable error (`:110`) — let
`InvalidCapabilityDeclaration` propagate; a plugin that fails to `ep.load()` (import error) also
fails loudly with a message naming the entry-point/distribution. Files: `registry.py`;
`tests/test_entry_point_discovery.py` (fake entry points via `importlib.metadata`
monkeypatch/fixture) asserting (a) well-formed plugin discovered, (b) bad-declaration raises at
`default_registry()`, (c) first/third-party `format_id` collision rejected. Part 3 §7.1 Revision
note if wording drifts.

## SLICE 16B — Discovery-proof test plugin (installable package under `tests/`)
Depends on 16A. Deliverable 2. **Greenfield — no installable sub-package precedent.** A minimal
real third-party format shipped as a **separate installable package** discovered purely via its
entry point (the P6 promise demonstrated). Model on `tests/_dummy_plugins.py` and
`tests/roundtrip/test_matrix_enumeration.py:30-66`, but **installed & discovered via entry point**:
`tests/fixtures/xtalate_toyfmt/` with its own `pyproject.toml` declaring
`[project.entry-points."xtalate.parsers"]`/`"xtalate.exporters"` (`MASTER_SPEC:1568-1572`), a real
`sniff()` (genuine score, not `0.0`), and a parser/exporter over a trivial toy text format. Matrix:
registered discovery makes it a **target** automatically; to be a two/three-hop **source** needs a
golden dir + `_GOLDEN_DIRS` entry — but golden dirs are governed (manifest + non-empty license).
**Recommend** a synthetic Apache-2.0 manifest, or keep it **target-only** (like the existing dummy)
to avoid governance coupling — decide and note. Files: the fixture package + a test that
`pip install`s it (or CI installs it) and asserts it appears in `default_registry()`/
`xtalate capabilities` and round-trips via the matrix; wire its install into CI.

## SLICE 16C — Docs (entry-point guide + R12) + v0.3 release
Depends on 16A/16B landed. Deliverables 3 & 4. **Release half (deliverable 4) is never cut** — if
discovery slips to v0.4, still tag v0.3 with discovery stated as deferred and the entry-point
*packaging* guide section slipping with the mechanism. **Docs:** update the add-a-format guide
(`CONTRIBUTING.md:113-126`) with an entry-point packaging step pointing at 16B's plugin; carry the
**R12 honesty clause verbatim** (SDK unstable until v1.0 — `CONTRIBUTING.md:13-18`, `README.md:25/
:139`, canonical `MASTER_SPEC:3245`); correct the stale module names in the spec's plugin worked
example (`MASTER_SPEC:1583-1587`: `xtalate.plugin_sdk`/`canonical_schema`/`capability_matrix` →
`xtalate.sdk`/`schema`/`capabilities`) with a Revision note. **Release:** version bump to `0.3.0`
in the three files (+`CITATION.cff` `date-released`); `CHANGELOG.md` rename `[Unreleased]` →
`[0.3.0] — <date>`, add M14/M15/M16 entries, add footer compare link
`[0.3.0]: …compare/v0.2.0...v0.3.0`; `README.md` scope statement (`:11-25`) retitle v0.2→v0.3,
update the format list to the **true registered count** (six only if M14 landed), change the
"does not do" to **CIF only, named as v0.4**; keep the SDK-not-frozen caveat. Tag + publish
(maintainer manual: `git tag v0.3.0`, `python -m build`, `twine upload`, GitHub release).

## After all 3 slices — v0.3 close
v0.3 tags when M12–M15 green, 16C's release half bumped version+CHANGELOG+README+CITATION and the
maintainer tagged/published, and discovery (16A/16B) either shipped or honestly deferred to v0.4.
Six-format core complete (XYZ, extXYZ, POSCAR, CONTCAR, XDATCAR, ASE traj); **CIF is v0.4** — do
not pull forward.
