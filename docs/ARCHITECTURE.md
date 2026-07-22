# Xtalate — Architecture Overview

Xtalate is the trusted translation layer between computational-chemistry file formats — a
converter that tells you exactly what it kept, what it lost, and why. This document is the
public design overview: the mission, the principles that constrain every decision, the pipeline,
the canonical data model, and the package layout. It is self-contained; you do not need any other
document to understand how Xtalate is put together.

For *how to build and contribute*, see the [Developer Guide](DEVELOPER_GUIDE.md). For the
*library and CLI surface*, see the [API Reference](API.md).

---

## 1. Mission and guiding philosophy

**Xtalate does one thing: loss-aware, fully transparent file conversion.** Every conversion
produces two structured, machine-readable records:

- a **Conversion Report** — what was preserved, dropped, transformed, or fabricated, and the
  reason for each; and
- a **Validation Report** — the output re-parsed and diffed against the source, proving the
  Conversion Report told the truth.

The guiding philosophy is **never silently lose scientific information.** The litmus test for any
design decision is: *if a user diffed the source and output files by hand, would anything surprise
them that Xtalate didn't already tell them about?* If yes, the design is wrong.

## 2. Scope and non-goals

Xtalate stores and translates data computed elsewhere. It is deliberately **not**:

- a molecular-dynamics package (it never integrates equations of motion),
- a DFT/quantum engine (it never computes energies or forces),
- a molecular editor (it never edits structures), or
- a visualization-first application (it never centres the product on rendering).

Visualization, File Repair, Analysis, and an AI assistant are **deferred secondary goals**, not
core work. Each is a *consumer* of the Canonical Object and the reports, and attaches later at a
defined extensibility seam (§8) — none is built into the conversion core.

Every augmentation Xtalate makes — a filled mass, an inferred symbol, a fabricated lattice,
generated velocities — is recorded as an Assumption and rendered in plain language in the
Conversion Report (e.g. *"Filled masses for 18 atoms using IUPAC standard atomic weights."*).
There are no silent fills, and no unrequested transformation even when it is standard practice:
recovery fabricates exactly what the user asked for and nothing more.

## 3. Design principles (P1–P6)

Every component and document is written against these six principles, referenced by ID throughout
the codebase and docs.

| ID | Principle |
|----|-----------|
| **P1** | **Every loss is reported, never assumed.** "The user probably doesn't need X" is never a valid reason for silence. |
| **P2** | **No parser talks to another parser.** All translation flows through one Canonical Model: `Native File → Canonical Object → Target Format`. No format-to-format shortcuts, ever. |
| **P3** | **Absence is information.** The schema distinguishes "never present in the source" (`None`) from "present with value zero/empty." |
| **P4** | **Recover explicitly, never guess.** Missing-but-required data is supplied only through an explicit Recovery Workflow, recorded as an Assumption. |
| **P5** | **Know the formats before converting.** The Capability Matrix predicts preservation/loss *before* conversion; Validation verifies it *after*. |
| **P6** | **Extensibility over optimization.** New formats/features attach at defined seams without core redesign; performance is reclaimed later behind stable interfaces. |

One sentence carries the whole project: **a conversion you can't audit is a conversion you can't
trust.**

## 4. Glossary (binding terms)

These terms are used verbatim across the codebase; they are not interchangeable with synonyms.

| Term | Meaning |
|---|---|
| **Canonical Model / Canonical Object** | The single internal schema every parser writes to and every exporter reads from. |
| **Parser** | Reads exactly one native format → produces a Canonical Object. Never writes files, never calls another parser, never defaults an absent field. |
| **Exporter** | Reads a Canonical Object → writes exactly one native format. Never reads native files. |
| **Capability Matrix** | Per-format, per-field data declaring what each format can/cannot express; drives loss prediction. |
| **Information Discovery Engine** | Inspects a file and reports what's present/absent (✓/✗ per canonical field) without converting it. |
| **Recovery Engine / Recovery Workflow** | Offers explicit, user-chosen ways to supply data a target format requires but the source lacks; every choice becomes an Assumption. |
| **Conversion Report** | Structured record of what a conversion kept, dropped, transformed, or assumed. |
| **Validation Report** | Post-conversion re-parse-and-diff result against the original Canonical Object, within tolerance. |
| **Discovery Report** | Output of the Information Discovery Engine. |
| **Provenance** | The Canonical Model's record of source software, parser version, and full conversion history (including all Assumptions). |
| **Plugin SDK** | Stable interface for third-party parsers/exporters/analysis modules; first-party formats hold no privileged API. |
| **Round-trip** | `Format A → Canonical → Format B → Canonical`, diffed within tolerance; the primary strategy for catching silent bugs. |
| **Phase 1 formats** | The seven target formats: XYZ, extXYZ, CIF, POSCAR, CONTCAR, XDATCAR, ASE trajectory. |

## 5. Architecture at a glance

Xtalate is a pipeline with a single **spine** surrounded by four **advisory subsystems** that
inspect or guide the spine but never bypass it.

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                            ↑        ↓
                        Information Discovery   Capability Matrix
                        Recovery Engine (explicit only) → Validation Engine
```

Every byte of scientific data flows along the spine. The advisors touch that flow only at defined
points:

- **Format Sniffer** — given raw bytes + filename, identifies the most likely format and its
  confidence, and selects a parser. It never parses scientific content.
- **Parser layer** (one per format) — reads one native format into a Canonical Object, marking
  every field *present* or *explicitly absent* (P3). A parser never reads another format, never
  calls another parser, and never defaults an absent field to zero.
- **Canonical Object** — the only thing that crosses the parser/exporter boundary.
- **Information Discovery Engine** — reads what the parser found and emits a ✓/✗ inventory
  (Discovery Report). Generic by construction: no per-format code.
- **Capability Matrix** — answers "can format *F* express canonical field *X*?" as queryable
  data, telling the exporter what the target can hold *before* it writes (P5).
- **Recovery Engine** — supplies target-required-but-source-absent fields *only* with an explicit
  user choice, recorded as an Assumption (P4). With no choice, the conversion **refuses** rather
  than inventing data.
- **Exporter layer** (one per format) — reads a Canonical Object and writes one native format. It
  never reads native files and never invents absent data (it triggers Recovery through the engine
  instead).
- **Validation Engine** — re-parses the output and diffs it against the source Canonical Object
  under a numeric tolerance profile, emitting a Validation Report. It runs as the final step of
  every completed conversion; there is no switch to skip it.

A conversion the engine declines is not an error — it is a **completed** result whose Conversion
Report has `status == "refused"`. A refusal is a first-class, reported outcome.

## 6. The Canonical Model and the absence convention (P3)

The Canonical Object is a pydantic-modeled schema (NumPy arrays in memory, nested JSON lists on
the wire) covering eight categories: Geometry, Simulation Cell, Trajectory, Dynamics, Electronic
Information, Simulation Metadata, Provenance, and User Metadata.

Its defining rule is the **absence convention**:

| State | Representation | Meaning |
|---|---|---|
| **Absent** | `None` | The source file did not contain this information at all. |
| **Present** | Actual value (including zeros) | The source contained it; the value is the value. |

Parsers are forbidden from defaulting: no zero velocities, no identity lattice, no invented
`energy = 0.0` to fill a gap. "Absent" and "present with value zero" are different states and the
schema keeps them different — this is what makes loss detectable rather than guessable.

When an upstream library manufactures a default (for example, ASE materializing a zero cell or
zero momenta), the parser must **launder** it back to `None`. Format-specific data that has no
canonical home is carried verbatim in namespaced `user_metadata` (e.g.
`custom_per_frame["xyz:comment"]`) rather than dropped.

## 7. Package layout and dependency layering

Xtalate ships as **one installable distribution** (`xtalate`) in a `src/` layout — not a
collection of separately packaged components. The scientific core is importable as a pure-Python
library with no web framework required.

```
src/xtalate/
  schema/         Canonical Model; depends on nothing else in xtalate/
  sdk/            stable parser/exporter base classes + capability models + streaming interface
  parsers/        one per format (xyz, extxyz, poscar, contcar, xdatcar, ase_traj); cif/ is a
                  four-stage package — the one format too large for a single module
  exporters/      one per format
  capabilities/   Capability Matrix: assembles + queries declarations
  discovery/      Information Discovery Engine + Format Sniffer + Discovery Report
  conversion/     Conversion Engine — orchestrates the pipeline + Conversion Report
  recovery/       Recovery Engine + workflows
  validation/     Validation Engine + Validation Report
  cli/            thin argparse presenter: inspect / convert / validate / capabilities
  registry.py     composition root: default_registry() = built-ins + entry-point discovery
  _time.py        the one UTC-timestamp helper
```

The dependency direction is strict and acyclic — `schema` depends on nothing; `sdk` depends only
on `schema`; `parsers`/`exporters`/`capabilities` depend on `schema` + `sdk`; the engines depend
on those; the CLI depends on the engines. **Nothing crosses from one parser to another.** This
direction is what *physically* enforces P2, and it is checked mechanically on every PR by an
[`import-linter`](https://import-linter.readthedocs.io/) layers contract (see the
[Developer Guide](DEVELOPER_GUIDE.md)).

## 8. Extensibility seams

The deferred secondary goals and all future formats attach without touching the conversion spine —
each is a *consumer* of an existing seam, never a modifier of it (P6):

| Future feature | Attachment seam |
|---|---|
| **New file formats** | A `ParserPlugin`/`ExporterPlugin` pair via the Plugin SDK plus one Capability Matrix declaration. Third-party formats are discovered through Python **entry points** (`xtalate.parsers` / `xtalate.exporters`) with no fork or edit to Xtalate. |
| **Visualization** | A read-only consumer of the Canonical Object and the reports; renders in a future UI route. |
| **File Repair** | Operates Canonical Object → Canonical Object between parse and export, each repair recorded in Provenance and the Conversion Report. |
| **Analysis** | Plugins that read a Canonical Object and emit results into namespaced `user_metadata`; they never touch parsers or exporters. |
| **AI assistant** | A reader of the already-machine-readable Discovery/Conversion/Validation reports. |

The through-line: **every future feature consumes an existing seam — the Canonical Object, the
reports, the Plugin SDK, or the Capability Matrix.** That property is the architectural promise the
project exists to guarantee.

## 9. Current status

Xtalate is a pure-Python **library + CLI**. **Phase 1 is complete**: all seven Phase 1 formats are
implemented and registered — XYZ, extXYZ, POSCAR, CONTCAR, XDATCAR, the ASE `.traj` format, and
CIF — and every pair among them converts. A frame-chunked streaming core keeps pipeline memory
sub-linear in the number of frames, so large trajectories convert at roughly constant memory with
a Conversion Report proven identical to the materialized path.

CIF is the one format whose reader is a **package rather than a module**
(`src/xtalate/parsers/cif/`), split into four stages with a one-way data flow: tokens (`_lexer`) →
a format-shaped document (`_document`) → CIF-level invariants (`_validate`, with `_symmetry` for
operation strings) → the Canonical Object (`_build`). The stage boundary is drawn by what each
stage is allowed to *know*: the first three know nothing of the Canonical Model, which is enforced
by two dedicated import-linter contracts rather than left as convention. Stage 2's output is
deliberately shaped like `gemmi.cif`'s `Document`/`Block` API, so adopting gemmi later means
deleting the first two stages and re-exposing the same calls, leaving the validation rules, the
error contract and the builder untouched. CIF is priced at more than the other six formats
combined, which is what makes that reversibility worth its cost.

The FastAPI **Service** layer and Next.js **Web UI** described as future destinations do not exist
yet; they attach to this same core without re-implementing it. Pre-1.0, a minor version may break:
the Plugin SDK is not frozen and the canonical schema version is still `0.x`.
