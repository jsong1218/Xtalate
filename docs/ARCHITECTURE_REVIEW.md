# ChemBridge — Architecture Review

> **Document status:** Advisory. A lead-architect review of `docs/MASTER_SPEC.md` (Parts 0–10 + Appendices A/B) and `docs/Incremental_Roadmap.md`, performed before any code exists. Findings are numbered and cited by Part/§ so each can be verified against the spec and accepted or rejected individually. This document changes nothing by itself; accepted findings should be applied to MASTER_SPEC.md as a Revision 1.2 note (per the spec's own convention, Part preface, Assembly note 6).
>
> Companion document: `docs/IMPLEMENTATION_PLAN.md` re-slices v0.1 into milestones, incorporating the recommendations below that the owner accepts.

---

## 1. Verdict

The architecture is fundamentally sound and unusually well-reasoned for a pre-code project. The load-bearing decisions — the absence convention (Part 2 §2), capability-matrix-driven conversion instead of O(n²) per-pair rules (Part 3 §4.3), the `supplied`-vs-`preserved` report split (Part 4 §2), refusal-as-default for fabricative scenarios (Part 4 §3.2), tolerance profiles with representational bounds (Part 5 §4.2), the thin-client rule (Part 7 §5.2), and reports-outliving-bytes (Part 9 §5.2) — are correct, mutually reinforcing, and each states a rejected alternative. **Nothing below recommends redesigning the pipeline.**

The problems are of three kinds, in descending severity:

1. **The spec contradicts the repository and itself in places that will become failing tests or blocked work in week 1** (§2 below). These are cheap to fix now and expensive to discover mid-build.
2. **Several decisions needed to write the first line of code were never made** — packaging shape, where the CLI/Discovery Engine/Sniffer live, the plugin-sdk dependency position (§3). The spec decides hard things (RQ vs Celery, CSRF strategy) while leaving easy-but-blocking things open.
3. **The v0.1 schedule does not survive its own arithmetic** (§5). The structure of the roadmap is good; the calendar is optimistic by roughly 40–60%.

There is also a project-shape risk worth naming once: the specification is ~65,000 words maintained by one student, and Part 10 §6 makes docs-vs-code drift a release blocker. Every unnecessary normative detail is future drift liability. Several recommendations below therefore *downgrade* spec text from "binding" to "design intent" rather than fixing it — deciding later, at the milestone where the decision is testable, is itself the fix.

---

## 2. Inconsistencies

### 2.1 Repository vs. spec

| # | Finding | Evidence | Severity |
|---|---|---|---|
| A1 | **LICENSE is MIT; the spec binds Apache-2.0.** | Part 10 §4.1 decides Apache-2.0 with explicit anti-MIT rationale (patent grant, NOTICE file for golden-corpus attribution). Repo `LICENSE` is MIT. | **High** — v0.1 is the first public release; relicensing after external contributions arrive is painful. Resolve before any code is committed. |
| A2 | **The eleven standalone docs (`00`–`10`) do not exist.** | MASTER_SPEC preface: standalone docs are "the editable source of truth… this merged file is regenerated from them." Part 1 §5 shows them in the repo tree. The roadmap titles itself "Binding supplement to `10_Roadmap.md`" — a file that doesn't exist. Only `MASTER_SPEC.md` and `Incremental_Roadmap.md` exist. | **High** — the project's own consistency rule ("the schema is edited in one place or not at all," Part 2 §9) currently points at eleven phantom files. |
| A3 | **MASTER_SPEC location.** Preface says the file is "committed at the root of the repository"; it lives in `docs/`. | Preface vs. git history (`1c80956`). | Low — cosmetic, but fix while fixing A2. |
| A4 | **README is a bare heading.** | Part 1 §5 expects "one-paragraph pitch + quickstart." | Low — expected pre-code; it is already on the roadmap's week-12 checklist. |

**Recommendation (A1):** pick one license *now*. If Apache-2.0 (the spec's reasoning is sound for this project), replace `LICENSE` and add the `NOTICE` file. If MIT is preferred, add a Revision note to Part 10 §4.1 reversing the decision with the new rationale — never leave a binding decision and the repo silently disagreeing.

**Recommendation (A2):** declare `MASTER_SPEC.md` the single editable source of truth. Delete the regeneration/standalone-set framing from the preface and the phantom `00–10` files from the Part 1 §5 tree. The cross-reference convention (`04 §3.3` → Part 4 §3.3) already works in the merged file; nothing else changes. Splitting back into standalone docs can happen at v1.0 if contributors ever want it — maintaining the fiction of two forms while only one exists guarantees drift.

### 2.2 Spec vs. spec

| # | Finding | Evidence | Severity |
|---|---|---|---|
| A5 | **Two conflicting "binding" version ladders.** Part 10 §1 defines v0.1 (18–22 dev-wk MVP), v0.2, v0.5, v1.0. The roadmap reassigns v0.1–v0.7 with different content per label, and says Part 10 "should gain a Revision note recording the new numbering" — that note was never added. Consequently "MVP" means two different things: Part 10's MVP = the roadmap's **v0.2**. Part 10 §2 says "Recovery … scenario catalog ships fully in MVP"; roadmap v0.1 ships two scenarios. | Roadmap header + §1; Part 10 §§1–2. | **High** — any reader (or AI planning agent, Persona 3) using Part 10 alone will build the wrong v0.1. |
| A6 | **Worked examples contradict the carry-through routing rule.** Part 2 §6.1 (a Revision 1.1 fix) routes the POSCAR title line to `user_metadata.custom_global["poscar:comment"]`, and Part 2 §8.2's *prose* says exactly that — but §8.2's *JSON* puts `"poscar:comment_line"` in `simulation.extra`, and Part 5 §6's validation example checks `simulation.extra['poscar:comment_line']`. The key name also drifts (`poscar:comment` vs `poscar:comment_line`). | Part 2 §6.1, §8.2; Part 5 §6. | **High** — Part 10 §4.6 makes these exact examples executable golden fixtures, so this contradiction becomes failing tests on day one of milestone M1/M3. |
| A7 | **DiscoveryReport cannot represent `mixed` presence.** Part 2 §3.11 defines the trichotomy `present / absent / mixed`; Part 3 §6.2's `FieldPresenceEntry.status` is `Literal["present", "absent"]`. A trajectory with per-frame energy in some frames only is unrepresentable in the Discovery Report — the exact situation `mixed` was added to express. | Part 2 §3.11 vs Part 3 §6.2. | **Medium** — add `"mixed"` (plus optional `present_frames`) to `FieldPresenceEntry` before the schema is implemented. |
| A8 | **Roadmap v0.1's "Validation Engine, identity round-trip only" is self-contradictory.** Runtime validation of the flagship extXYZ→POSCAR conversion *is* a cross-format half round-trip (Part 5 §1: re-parse output B, diff against expected object). "Identity only" can only describe the *test suite*. As written, a literal reading would ship a v0.1 that cannot validate its own headline conversion. | Roadmap §2.3 vs Part 5 §1. | **Medium** — reword: v0.1 ships the full runtime validation path; the *test-suite* round-trips are identity-only, with two-hop suites in v0.2. |
| A9 | **Capability-path wildcard is undefined.** Part 3 §4.1: every `fields` key "must be a valid canonical path; the registry rejects declarations with unknown paths." The POSCAR example in §4.2 uses `"simulation.*"`. | Part 3 §4.1 vs §4.2. | **Medium** — one sentence fixes it (e.g., "a trailing `.*` denotes all leaf paths under the prefix; the registry expands it at load"). |
| A10 | **`electronic.total_spin` is missing from the Part 3 §3 format table** while present in the schema (Part 2 §3.7) and the Discovery example (Part 3 §6.3). The table-vs-declaration sync test (Part 8 §1.1) would flag this on its first run. | Part 3 §3 table. | Low — add the row (likely `◐²` for extXYZ/ASE traj, `○` elsewhere). |
| A11 | **`schema_version: "1.0.0-draft"` (roadmap §2.3) vs `"1.0.0"` (every Part 2 example), and Part 2 §5's migration semantics never define pre-release ordering.** A migration registry keyed on semver needs to know where `1.0.0-draft` sorts. | Roadmap §2.3 vs Part 2 §§3.2, 5, 8. | **Medium** — recommend an explicit pre-1.0 series: v0.1 ships `schema_version: "0.1.0"`, frozen `"1.0.0"` at product v1.0 (this also matches Part 10 §6 item 3, "schema tagged 1.0.0" as a v1.0 deliverable, which implies it is *not* 1.0.0 before then). |
| A12 | **File-name drift:** the roadmap is `docs/Incremental_Roadmap.md`; project communication (including the request for this review) refers to `docs/ROADMAP.md`. | — | Low — rename to `docs/ROADMAP.md` or standardize references; pick one. |

---

## 3. Missing engineering decisions

These are decisions the spec *needs* but never makes. Each blocks or shapes milestone M0–M2 of the implementation plan. Recommended resolutions are stated so accepting this review resolves them; each should be recorded in the spec's Revision 1.2 note with the spec's own rejected-alternative discipline.

| # | Missing decision | Why it blocks | Recommended resolution |
|---|---|---|---|
| B1 | **Where the CLI lives, and on what framework.** Appendix A binds the CLI surface; neither Part 1 §5's repo tree nor the `packages/` list contains a CLI home. No framework is chosen. | Roadmap week 11 cannot start without it; entry-point (`chembridge` console script) must be declared in packaging (M0). | A `chembridge.cli` module inside the main distribution (it is a thin presenter over `packages/*`, same rule as the API layer). Framework: **argparse** (stdlib, zero deps, adequate for 4 subcommands) or **Typer** if help-text ergonomics matter; either is defensible — pick in M0 and record it. |
| B2 | **Where the Information Discovery Engine and Format Sniffer live.** Part 3 specifies both in detail; the package list (canonical-schema, parsers, exporters, capability-matrix, conversion, recovery, validation, plugin-sdk) has no slot for either. | Both are v0.1 week-3/week-4 deliverables. | Sniffer + registry + Discovery Engine in a `chembridge.discovery` module (or inside `parsers`): all three are generic-by-construction consumers of the plugin interface (Part 3 §6.1), so they belong together, above the format implementations, below `conversion`. |
| B3 | **plugin-sdk's position in the dependency graph — currently circular.** Part 1 §5.1's acyclic rule never mentions plugin-sdk. Yet `ParserPlugin.capabilities()` returns `FormatCapabilities` (defined in capability-matrix, Part 3 §4.1), `ParseResult` wraps `CanonicalObject`, *and* the capability-matrix registry "is assembled from each plugin's declarations at registry load" — so plugin-sdk depends on capability-matrix which loads plugin-sdk implementations. | The import-graph lint (Part 8 §1.1, "the CI teeth behind P2") cannot be written until the graph is acyclic on paper. | Split types from machinery: `FormatCapabilities`/`FieldCapability`/`CapabilityLevel` are pure data models — move them into **plugin-sdk** (or canonical-schema) alongside `ParseResult`/`ParseIssue`; the capability-matrix package keeps the *registry and query API*, sitting above plugin-sdk. Resulting order: `canonical-schema → plugin-sdk → {parsers, exporters} → capability-matrix/discovery → {conversion, recovery, validation} → cli`. |
| B4 | **Packaging shape: one distribution or eight?** Part 1 §5 shows eight hyphenated `packages/*`; Part 9 §3 says they publish "to PyPI as the `chembridge` distribution" (singular). Hyphenated names aren't importable; nothing defines import names, build backend, src-layout, dependency manager, or minimum Python version. | Blocks week 1 entirely — `pyproject.toml` is the first deliverable. | See §4.1 below: **one distribution, subpackages as modules**. Concretely: single `pyproject.toml`, `src/chembridge/{schema,sdk,formats,capabilities,discovery,conversion,recovery,validation,cli}/`, Python ≥3.11, hatchling or setuptools backend, `uv` or plain pip for dev. Record the choice + rejected alternative in M0. |
| B5 | **Per-format implementation strategy: hand-rolled vs ASE/pymatgen-wrapped.** Part 3 §2 says parsers "may delegate" to ASE/pymatgen; the roadmap's risk section suggests "wrapping ASE I/O and laundering" for POSCAR. The choice per format drives the laundering-test burden, dependency pinning, and whether ASE/pymatgen are v0.1 dependencies at all. | Shapes M3's estimates and the M0 dependency list. | Decide per format in M0. Suggested default: **hand-rolled XYZ** (trivial format; avoids laundering entirely), **ASE-backed extXYZ** with the laundering suite (the extXYZ `Properties=` grammar is the one place battle-tested code earns its keep), **hand-rolled POSCAR/CONTCAR** (well-documented format; hand-rolling avoids pymatgen as a v0.1 dependency and gives full control of selective-dynamics → `Constraint` mapping). This makes v0.1 depend on ASE only. |
| B6 | **NumPy-in-pydantic array types and canonical JSON number formatting.** Part 2 §1 assumes "pydantic custom types handling validation and JSON serialization as nested lists" — nontrivial to design (Annotated types, shape validation against N/F, dtype policy). Separately, float64→JSON→float64 round-trip determinism is **load-bearing for golden-file equality** (Part 8 §3: `expected.canonical.json` compared on every PR) and is nowhere specified. | Blocks M1; silent nondeterminism here poisons the golden corpus. | Specify in M1: arrays serialize via Python `repr`-shortest float formatting (`json.dumps` default), which round-trips float64 exactly; golden comparisons deserialize both sides and compare arrays with `==` (exact) — never compare JSON text. One paragraph in the spec ends the ambiguity. |
| B7 | **Import-graph lint tooling.** Named as CI enforcement of P2 (Part 8 §1.1); roadmap week 1 has a "dependency-direction lint stub" with no definition. | M0 CI skeleton. | **import-linter** with a `contracts` file mirroring the B3 graph; runs in the PR lint stage from week 1 (a real check is barely more work than a stub). |
| B8 | **Smaller items** (resolve in passing): `TrajectoryMetadata` now holds a single optional field (`timestep`) after `frame_count` became derived — either keep it (fine: it is the seam for future trajectory metadata; say so) or fold `timestep` to root. `Constraint.parameters: dict[str, Any]` needs a JSON-serializability bound. Sniffer confidence values are uncalibrated across the 4 formats (the golden corpus pins outcomes, Part 3 §6.1, which suffices — but say the numbers are ordinal, not probabilistic). | — | One-line clarifications each. |

---

## 4. Unnecessary complexity and MVP simplifications

The spec's instinct to defer (Roadmap §10's postponed-practices table) is excellent. These findings push the same instinct further.

### 4.1 One distribution, not eight packages (accept before M0)

Eight separately-packaged monorepo Python packages is polyrepo-grade ceremony inside a monorepo, for a solo student. The *architectural* value — enforced boundaries, P2 — comes from the **import graph**, not from packaging metadata. Recommendation:

- Ship **one installable distribution** `chembridge` with the components as subpackages (`chembridge.schema`, `chembridge.formats`, …).
- Keep the boundaries **mechanically enforced** by import-linter (B7) — this is the actual P2 teeth, and it works identically on modules.
- Re-split into separate distributions at v1.0 *if* the SDK freeze creates a reason (e.g., a slim `chembridge-sdk` for plugin authors). Packaging seams are cheap to add later; eight `pyproject.toml`s, eight version numbers, and cross-package editable installs are weekly friction now.

This is a change to Part 1 §5's tree, not to any component boundary.

### 4.2 Defer entry-point plugin discovery (keep the ABCs)

Shipping the `ParserPlugin`/`ExporterPlugin` ABCs and the `ParseResult` error contract in v0.1 is the right call (retrofitting an SDK under four parsers is the rewrite the roadmap fears). But `importlib.metadata` entry-point loading, third-party declaration validation at registry startup, and the `chembridge.parsers` entry-point group (Part 3 §7.1) serve **zero users before v0.3** — the roadmap itself says parser contributions are unrealistic before then. v0.1's registry should be an explicit list (`register(XyzParser())`, four lines). Entry-point discovery is an additive change to the registry in v0.3, behind the same interfaces.

### 4.3 Downgrade Parts 6, 7, 9 from "binding" to "design intent"

The service/UI/ops parts are specified to an implementation level of detail (double-submit CSRF tokens, argon2id, Alembic migration policy, RQ worker semantics, DR restore drills, Prometheus metric names) **12–24 months before they will be built** (roadmap v0.5–v0.7). Two problems:

1. The ecosystem will move; some of these decisions will be re-litigated at build time regardless of what the doc says.
2. Part 10 §6 item 7 makes docs-vs-code drift a **release blocker** — so every prematurely-bound detail is a future blocker the project planted for itself.

Recommendation: add one line to each of Parts 6, 7, 9's status headers: *"Binding for contracts and vocabulary (endpoint names, report schemas, job states, design principles); implementation detail below §X is design intent, re-validated when the version that builds it begins."* The genuinely load-bearing content — the error envelope, job-state enum, refusals-are-200, endpoint table, ✓/✗/◆ language — stays binding; the operational minutiae stop being drift liability.

### 4.4 v0.1 scope trims (reflected in the implementation plan)

- **Named tolerance profiles only** (`default`/`strict`/`loose`); defer custom-table files (Part 5 §4.4) to v0.2. The CLI flag stays `--tolerance-profile NAME`; the `FILE` form is additive later.
- **Recovery choices in v0.1:** `missing_lattice` = `manual_input` + `bounding_box`; `frame_selection` = `first`/`last`/`index`. The roadmap already trims to this (week 9); make it explicit that `upload_reference`, `non_periodic`, and `split_all` are v0.2, and that the *computed option list* mechanism must still exclude unoffered choices honestly (a refusal report lists only options that exist in this version).
- **Sniffer:** content heuristics for exactly 4 formats plus the POSCAR⇄CONTCAR filename rule (Part 3 §6.1) — resist generalizing the scoring machinery beyond what four formats need.

### 4.5 One cheap addition (complexity worth buying)

**Run the completeness invariant as a runtime assertion in the Conversion Engine from day one.** The property-test harness is correctly deferred to v0.2, but the invariant itself (every source-present path in `preserved ∪ removed`; every `supplied` path absent-on-source and traced to an Assumption — Part 4 §2) is checkable in ~20 lines at report-finalization time. It is the product's core promise; an `InvariantViolation` raised in development catches report bugs months before the property test exists. Cost: an afternoon in M4.

---

## 5. Roadmap realism

### 5.1 The v0.1 estimate contradicts the roadmap's own arithmetic

- Part 10 §1 prices its MVP at **18–22 experienced part-time dev-weeks** at 10–15 h/week ≈ **180–330 hours**.
- Roadmap §1 defines v0.1 as "the first ~60% of Part 10's MVP" ≈ 110–200 hours *at experienced pace*.
- Roadmap §0 applies a **1.5× student multiplier** to everything: ≈ **165–300 hours**.
- Roadmap §2 then budgets v0.1 at **12–13 weekends × ~9 h ≈ 110–120 hours** — below even the *un-multiplied* figure.

The honest range at the stated cadence is **16–24 weekends**, i.e. one-and-a-half semesters, not one. This is not a structural flaw — the milestone ordering, the formats-front-loaded buffer, the "cut format edge cases, never report completeness" slip rule, and every-version-is-a-resting-state are all genuinely good planning — but the calendar should be re-baselined *before* it starts slipping, because a plan that slips in week 5 demoralizes in a way a plan that honestly says "two semesters" does not.

### 5.2 Where the optimism concentrates

| Roadmap week | Deliverable | Assessment |
|---|---|---|
| 1–2 (schema) | 8 categories + validators + serialization | Plausible **if** B6 (array types) is pre-decided; otherwise week 1 becomes a pydantic-and-NumPy research project. |
| 5 (extXYZ) | parser + exporter + golden + round-trip in ~9 h | **Most under-budgeted week.** The `Properties=` grammar, arbitrary per-atom columns, laundering suite, and key-value comment parsing are a 2–3 weekend job even ASE-backed. |
| 9 (recovery) | bright-line classification + 2 scenarios + refusal + Assumption recording in ~9 h | Under-budgeted ~2×; this is the code the whole philosophy rides on and it deserves unhurried tests. |
| 12 (release) | CI, README, demo, packaging polish | Plausible, and the polish-creep warning (roadmap §2.6) is exactly right. |
| 13 (buffer) | one buffer weekend for a 12-week plan | Insufficient; format edge-case debt alone will consume it (the roadmap admits this: "it will exist"). |

### 5.3 What to keep unchanged

The v0.2-as-winter-break sizing, CIF isolated in v0.4 ("mixing CIF with other work is how CIF eats a semester" — correct), the v0.5 API as a consecutive-days summer block (the job state machine genuinely is the piece that shouldn't be built in weekend fragments), and the deferral table in §10 are all well-reasoned. No changes recommended from v0.2 onward beyond inheriting v0.1's re-baselined end date.

### 5.4 Recommendation

Re-baseline v0.1 to **16–20 weekends** with explicit go/no-go checkpoints (the implementation plan's milestones M1–M6 provide them), and pre-authorize the fallback: if M3 (formats) runs long, v0.1 may ship with extXYZ read-only or deferred entirely — XYZ→POSCAR alone still demonstrates the full pipeline including the flagship `missing_lattice` refusal. Deciding the cut *now*, calmly, beats deciding it in week 10 under deadline pressure.

---

## 6. Strengths worth preserving unchanged

Recorded so that "review" is not read as "rewrite":

1. **The absence convention** (Part 2 §2) and its enforcement via laundering tests (Part 3 §2, Part 8 §1.1) — the single best idea in the spec, and the correct thing to build first.
2. **Capability-matrix-driven conversion** — O(n) declarations + one generic diff, with the matrix doubling as the definition of round-trip comparability (Part 5 §5).
3. **The three-way hazard model** (bulk-reductive / selective-reductive / fabricative, Part 4 §3.1) and the categorical no-defaults rule — the "refusal is the default" resolution of the timeout question is exactly right.
4. **`supplied` as a third report category** with `from_assumption` traceability — structurally prevents fabricated data reading as source data.
5. **Refusals as HTTP-200 completed jobs** (Part 6 §1) — unusual and correct for this product.
6. **Validation validates the report, not "no loss"** (Part 5 §1) — the framing that makes `passed` meaningful.
7. **The roadmap's slip rule** — "a converter that handles fewer files honestly beats one that handles more files silently" applied to schedule pressure.

---

## 7. Recommended actions before implementation (prioritized)

| Priority | Action | Resolves | Effort |
|---|---|---|---|
| 1 | Decide the license; make `LICENSE` and Part 10 §4.1 agree (add `NOTICE` if Apache-2.0). | A1 | minutes |
| 2 | Declare MASTER_SPEC.md the single source of truth; remove the standalone-docs fiction and fix the Part 1 §5 tree; rename or re-reference the roadmap file. | A2, A3, A12 | <1 h |
| 3 | Add a Revision 1.2 note to MASTER_SPEC adopting the roadmap's version ladder and the terminology rule ("MVP" = v0.2; v0.1 = first public release), plus the spec-vs-spec fixes: worked-example carry-through keys (A6), `mixed` in `FieldPresenceEntry` (A7), capability wildcard semantics (A9), `total_spin` table row (A10), schema pre-1.0 versioning `0.1.0` (A11), roadmap validation wording (A8). | A5–A11 | ~2–3 h, one editing pass |
| 4 | Make the M0 engineering decisions and record them (with rejected alternatives, per house style): packaging shape (§4.1/B4), module homes for CLI/discovery/sniffer (B1, B2), acyclic graph with plugin-sdk placed (B3), per-format strategy (B5), array serialization + golden equality semantics (B6), lint tooling (B7). | B1–B8 | the first work session of M0 |
| 5 | Downgrade Parts 6/7/9 implementation detail to "design intent — re-validate at build time." | §4.3 | <1 h |
| 6 | Adopt the v0.1 scope trims (§4.4), the runtime completeness assertion (§4.5), and defer entry-point discovery to v0.3 (§4.2). | §4 | reflected in IMPLEMENTATION_PLAN.md |
| 7 | Re-baseline v0.1 to 16–20 weekends with the pre-authorized extXYZ cut-line (§5.4). | §5 | reflected in IMPLEMENTATION_PLAN.md |

Items 1–3 are spec hygiene and take one sitting. Items 4–7 are absorbed into `docs/IMPLEMENTATION_PLAN.md`, which assumes they are accepted (each dependency is flagged there explicitly).
