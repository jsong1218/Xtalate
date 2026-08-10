# Xtalate

[![CI](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml/badge.svg)](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](CHANGELOG.md)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**The trusted translation layer between computational-chemistry file formats — a converter that tells you exactly what it kept, what it lost, and why.**

Every conversion produces a structured **Conversion Report** (what was preserved, dropped, or fabricated, and the reason for each) and an automatic **Validation Report** (the output re-parsed and diffed against the source to prove the report told the truth). The guiding rule is simple: *never silently lose scientific information.* If you diffed the input and output by hand, nothing should surprise you that Xtalate didn't already tell you about.

## What it is

Xtalate does **one thing**: loss-aware, fully transparent conversion between structure and trajectory file formats. It is a single Python package with four ways to use it, all over the same engine:

- **A library** — parse a file into one Canonical Object, convert it, read the reports.
- **A CLI** (`xtalate`) — `inspect` / `convert` / `validate` / `capabilities`, JSON-emitting and CI-native.
- **An HTTP service** (`/v1`) — a FastAPI app that exposes the engine as async jobs; ships as the optional `service` extra.
- **A Web UI** — a Next.js front end that walks upload → inspect → convert → recover → record → download, rendering the engine's reports verbatim.

The scientific logic lives in the engine and nowhere else; the service and the UI are thin presenters that embed the report models unchanged. Visualization, structure editing, MD, and analysis are explicitly **out of scope** — Xtalate stores and translates data computed elsewhere.

## Formats

Seven formats, every one **read *and* written**, so every pair among them converts (the nightly suite runs the full 7 × 7 matrix):

**XYZ** · **extended XYZ** (ASE-backed) · **POSCAR** · **CONTCAR** (incl. the velocity block, Cartesian + Direct) · **XDATCAR** · **ASE `.traj`** · **CIF**.

**CIF is treated as real crystallography.** Cell parameters become lattice vectors, fractional coordinates become Cartesian at the parser boundary, and symmetry is expanded **from the operations the file declares** — parsed as exact affine maps over rationals, with sites on a symmetry element merged on a physical 0.05 Å threshold. A file that names a space group but declares *no* operations is **refused**, never read as a partial structure. Site occupancy is a first-class canonical field (`atoms.occupancies`); a target that cannot represent a partial occupancy says so in the report rather than dropping it silently. The exporter writes every atom explicitly under an identity symmetry loop with no space-group symbol — the coordinates it emits are the already-expanded cell, and any symbol above them would assert a setting they no longer encode.

## What every conversion gives you

- **Inspect first.** The Information Discovery Engine reports a ✓/✗ inventory of which canonical fields a file actually contains, each annotated with the format's capability — no conversion required.
- **Predict loss before writing.** A per-format **Capability Matrix** tells the exporter what the target can hold *before* it writes, so loss is predicted (**P5**), not discovered after the fact.
- **Recover explicitly, never guess.** When a target needs a field the source lacks — a lattice, velocities, masses — or can hold only one frame, you supply a preset choice and it is recorded as an **Assumption**. With no choice, the conversion **refuses** rather than inventing data (**P4**). Fabrication is exactly what you asked for and nothing more.
- **Validate, always.** Every completed conversion is re-parsed through the ordinary reader and diffed against the expected object under a numeric tolerance profile (`default` / `strict` / `loose`, or a custom table). There is no switch to skip it.
- **Absence is information (P3).** The Canonical Model distinguishes "the source never had this" (`None`) from "the source had it, and the value is zero." Parsers never default an absent field.
- **Scale to large trajectories.** A frame-chunked streaming core keeps pipeline memory sub-linear in the number of frames — a 10⁴-configuration XDATCAR streams at roughly constant memory and yields a report byte-identical to the materialized path.
- **Third-party formats via plugins.** A parser/exporter shipped in a separate package is discovered automatically through Python entry points (`xtalate.parsers` / `xtalate.exporters`), with no fork or edit; it joins sniffing, discovery, conversion, and validation on equal footing. First-party formats hold no privileged API.

## Install

```bash
pip install xtalate                 # the library + the `xtalate` CLI
pip install "xtalate[service]"      # add the FastAPI /v1 service layer
# or, from a checkout:
pip install -e ".[dev]"
```

Requires Python ≥ 3.11. The only scientific dependency is ASE (for extended XYZ and the ASE `.traj` format); NumPy and pydantic power the Canonical Model, and PyYAML parses custom tolerance tables and corpus manifests.

## Quickstart (CLI)

**Inspect** a file — see what's actually inside it, before converting anything:

```console
$ xtalate inspect water_traj.xyz
File:   water_traj.xyz  (164 bytes)
Format: Plain XYZ [xyz]  confidence 0.9
Structure: 2 frame(s) × 3 atoms; species O, H

Canonical fields (✓ present / ✗ absent / ◐ mixed · read capability):
  ✓ atoms.symbols                    [full]  — O, H, H
  ✓ atoms.positions                  [full]  — 2 frame(s) × 3 atoms, Cartesian (Å)
  ✗ atoms.masses                     [none]
  ✗ cell.lattice_vectors             [none]
  … (16 canonical leaf paths, each shown present or absent)
```

**Convert** a 2-frame, lattice-less XYZ trajectory to POSCAR. POSCAR needs a single structure *and* a lattice, so we supply two explicit recovery choices; each becomes a recorded Assumption:

```console
$ xtalate convert water_traj.xyz --to poscar -o POSCAR \
    --recover frame_selection=last \
    --recover missing_lattice=bounding_box,padding_ang=5.0
Conversion Report  [final · completed · permissive]
  xyz → poscar
  preserved (2): atoms.symbols, atoms.positions
  removed (2):   custom_per_frame['xyz:comment']; 1 dropped frame
  supplied (2):  cell.lattice_vectors, cell.pbc  (from A2)
  assumptions (2):
    ~ A1 frame_selection=last:   frame 1 of 2 retained …
    ~ A2 missing_lattice=bounding_box:  axis-aligned box + 5.0 Å padding …

Validation Report  [passed]  (tolerance profile: default)
  ✓ atom_count · ✓ species_preservation · ✓ positions_rmsd · ✓ lattice_consistency
  ✓ frame_count · – numeric_field_fidelity · ✓ metadata_preservation
  ✓ absence_conformance · ✓ report_consistency
```

Without the `--recover` flags the same command **refuses** (exit code 2) and prints exactly which decisions are needed — a refusal is a first-class, reported outcome, never a silent default. Exit codes make the CLI CI-native: `0` ok · `2` refused · `3` validation failed · `4` parse error · `5` warnings under `--mode strict` · `1` usage error. Any command accepts `--json` to emit the report schema verbatim. See the [CLI reference](docs/cli.md).

## Quickstart (library)

```python
from xtalate.registry import default_registry
from xtalate.conversion import ConversionEngine

registry = default_registry()
with open("in.extxyz", "rb") as fh:
    source = registry.get_parser("extxyz").parse(fh, filename="in.extxyz").canonical

result = ConversionEngine(registry).convert(
    source, source_format_id="extxyz", target_format_id="poscar",
)
print(result.report.model_dump_json(indent=2))   # the Conversion Report
print(result.validation.status)                   # "passed"
with open("POSCAR", "wb") as fh:
    fh.write(result.output)
```

A complete, runnable example is in [`examples/convert_extxyz_to_poscar.py`](examples/convert_extxyz_to_poscar.py).

## Quickstart (HTTP service)

Run a dependency-free instance (SQLite + local filesystem, jobs executed in-process):

```bash
pip install "xtalate[service]"
python -m backend                       # http://localhost:8000
```

…or bring up the full stack — API, worker, PostgreSQL, MinIO, Redis — with one command:

```bash
docker compose up --build --wait
curl -s "http://localhost:8000/v1/health?ready=true"
```

Conversion is an async job; a refusal comes back as a **completed HTTP-200 job**, not an error:

```bash
BASE=http://localhost:8000/v1
FILE_ID=$(curl -s -F "file=@in.extxyz" "$BASE/upload" | jq -r .file_id)
JOB=$(curl -s "$BASE/convert" -H 'content-type: application/json' \
  -d "{\"file_id\":\"$FILE_ID\",\"target_format_id\":\"poscar\"}" | jq -r .job_id)
curl -s "$BASE/jobs/$JOB" | jq '.state, .result.conversion_report.status'
CID=$(curl -s "$BASE/jobs/$JOB" | jq -r .result.conversion_id)
curl -s "$BASE/download/$CID" -o POSCAR
```

Reports **outlive the bytes** they describe: input and output expire on independent lifecycle windows while `GET /v1/conversions/{id}` still serves both reports. The full flow — including interactive recovery (`allow_recovery` → pause → resume) — is walked with `curl` in [`docs/API.md`](docs/API.md), and the machine-readable contract is the committed [`docs/openapi.json`](docs/openapi.json).

## Web UI

A faithful web front end over `/v1` — the whole workflow in a browser, with the loss report as the thing you cannot miss. It is a **presentation layer only** (carries no scientific logic): every number, code, and reason on screen is the engine's own, rendered verbatim. The wizard is four steps — upload & inspect, preview the predicted loss, convert & recover (one decision card per unresolved scenario, no option preselected, the exact Assumption shown before you confirm it), then a consolidated record whose outcome header is quantitative ("Converted — 7 fields removed", never "Done!") and whose download control sits *below* the loss summary by layout law. Two read-only pages — `/formats` (the Capability Matrix, generated from `GET /v1/capabilities`) and `/history` — make the engine's own knowledge browsable, and the whole `docs/` corpus renders as an in-app docs site.

Self-hosting is the primary supported deployment: a hardened [`docker-compose.prod.yml`](docker-compose.prod.yml) points at external Postgres and S3-compatible storage. See the **[self-hosting guide](docs/self-hosting.md)**.

## How it works

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                             ↑        ↓
                         Information Discovery   Capability Matrix
                         Recovery Engine (explicit only) → Validation Engine
```

The **Canonical Object** is the only thing that crosses the parser/exporter boundary — no parser ever calls another parser, and no conversion takes a format-to-format shortcut (**P2**). That single spine is what makes **adding a format O(1)** in the number already present: each of XDATCAR, ASE `.traj`, and CIF arrived as one parser and one exporter plus a Capability Matrix row, joining sniffing, discovery, conversion, validation, and the full n×n round-trip matrix without a single edit to any other format.

The design and its principles are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the library and CLI surface in [`docs/API.md`](docs/API.md); building and extending Xtalate in [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md). Architectural decisions (the D-log) and the master specification are maintained privately; public commits may reference decision IDs. If you need the rationale for a particular decision, open an issue.

## Versioning and stability

Xtalate follows [Semantic Versioning](https://semver.org/) (the current release is shown in the badge above), and the version number protects a **named public surface**: within a major series each of these evolves **additively only** — new formats, scenarios, optional fields, and hooks arrive with safe defaults; nothing already documented is removed, renamed, or given a new meaning. Anything that would break one of them waits for the next major version, with migration notes.

- **The canonical schema** — field names, shapes, unit conventions, and absence semantics (**P3**) of the eight-category Canonical Model.
- **The report schemas** — `DiscoveryReport`, `ConversionReport`, `ValidationReport`, embedded verbatim in every result.
- **The plugin SDK ABCs** — `ParserPlugin`, `ExporterPlugin`, the streaming surface, `ParseResult`/`ParseIssue`/`ParseError`, and `FormatCapabilities` (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- **The `/v1` REST surface** — endpoints, response envelopes, and error codes; [`docs/openapi.json`](docs/openapi.json) is its versioned, machine-readable form.
- **The documented CLI** — the four subcommands, their flags, the `--json` convention, and the exit-code ladder `0`–`5` (see the [CLI reference](docs/cli.md)).

The internal, `_`-prefixed surface is explicitly **not** part of the contract.

**Two version axes, moving under distinct rules.** The **product version** (`xtalate.__version__`, `pyproject.toml`, `CITATION.cff` — guarded to agree) is the SemVer of the distribution and bumps on every release. The **canonical `schema_version`** is the on-the-wire version of the Canonical Model, stamped into every object; it bumps only when the schema itself changes, and always behind a **real migration** — an older stored object is carried forward on load and gains a `ConversionRecord(operation="migrate")`, never silently. A release can ship without a schema change, so the two numbers are decoupled by design.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .    # lint + format
mypy                                     # types (strict)
lint-imports                             # acyclic package layering (P2)
pytest                                   # tests
```

CI runs this matrix on Python 3.11 and 3.13, plus the corpus governance suite over both corpus roots (manifest schema + license, source hashes, `ATTRIBUTIONS.md` regeneration) and a coverage ratchet.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The invited path is **corpus contributions**: real, licensed sample files that harden the converter. A **golden** case (`tests/golden/`) asserts what a file *should* produce and needs an expectation you verified by hand; a **wild** case (`tests/wild/`) is a real third-party file asserting what it *does* produce — the exact set of issue codes plus the composition it declares for itself — so it needs a triage rather than a derivation. Both need a manifest and a license; no manifest, no license, no merge. Parser plugins are welcome too — the plugin SDK is a stable contract (see [CONTRIBUTING.md](CONTRIBUTING.md) for the stability promise and its scope).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
</content>
</invoke>
