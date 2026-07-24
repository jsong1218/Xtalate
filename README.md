# Xtalate

[![CI](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml/badge.svg)](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**The trusted translation layer between computational-chemistry file formats — a converter that tells you exactly what it kept, what it lost, and why.**

Every conversion produces a structured **Conversion Report** (what was preserved, dropped, or fabricated, and the reason for each) and an automatic **Validation Report** (the output re-parsed and diffed against the source to prove the report told the truth). The guiding rule is simple: *never silently lose scientific information.* If you diffed the input and output by hand, nothing should surprise you that Xtalate didn't already tell you about.

## What v0.5 does

**The whole engine, now over HTTP — and Phase 1 stays complete: all seven formats read *and* write.**

New in v0.5, the **Service layer**: a FastAPI application exposes the same engine under `/v1` as
async jobs (`inspect` / `convert` / `validate` → poll `GET /v1/jobs/{id}` → retrieve). It adds
nothing scientific — it is a thin presenter that embeds the pydantic report models **verbatim** — and
it carries the two rules the whole product turns on: a **refused conversion is a completed HTTP-200
job** (`ConversionReport.status == "refused"`), never a 4xx; and an interactive recovery pause
(`awaiting_recovery`) that **expires to a refusal, never a silently-applied default**. Reports
**outlive the bytes** they describe (input and output expire on independent lifecycle windows while
`GET /v1/conversions/{id}` still serves both reports), uploads are size-gated (`413`), callers are
rate-limited (`429` + `Retry-After`), and an instance may require a static API key. `docker compose
up` brings up the full Tier 1 stack (API + worker + PostgreSQL + MinIO + Redis); see the
[HTTP quickstart](#quickstart-http-service) and the committed [`docs/openapi.json`](docs/openapi.json)
contract. The library and CLI below are unchanged.

- **Formats** (read *and* write): plain **XYZ**, **extended XYZ** (ASE-backed), **POSCAR**, **CONTCAR** — including the POSCAR/CONTCAR **velocity block** (Cartesian + Direct) — **XDATCAR**, the **ASE `.traj`** format, and **CIF**. Every pair among them converts, and the nightly matrix runs all 7 × 7.
- **CIF, with crystallography taken seriously.** Cell *parameters* → lattice vectors, fractional → Cartesian at the parser boundary, and **symmetry expansion from the operations the file declares** — parsed as exact affine maps over rationals, so a translation written `1/3` is a third, with sites on a symmetry element merged on a physical 0.05 Å distance. A file that names a space group but declares *no* operations is **refused**, never read as a partial structure: supplying the operations from space-group tables would be data the file never stated, and the failure it prevents is a conversion that silently yields a fraction of the atoms. Occupancy and declared formal charges are carried, and the exporter writes every atom explicitly under a one-entry identity symmetry loop with **no space-group symbol at all** — not even `P 1` — because the coordinates it writes are the already-expanded full cell, and any symbol above them would assert a setting they no longer encode. A source's symbol is reported as removed rather than echoed.
- **Validated against real files, not just fixtures.** A corpus of Crystallography Open Database entries is vendored verbatim and asserted against the composition each file declares for its own unit cell (`_chemical_formula_sum` × `_cell_formula_units_Z`) — so a symmetry bug is caught by contradicting the very file that produced it, rather than by a number someone hoped was right. It found two loss-reporting defects that seven milestones of synthetic fixtures had not.
- **Scales to large trajectories** — a frame-chunked streaming core makes pipeline memory **sub-linear in the number of frames**: `convert` streams a 10⁴-configuration XDATCAR at roughly constant memory and produces a Conversion Report **byte-identical** to the materialized path. XDATCAR and ASE `.traj` are streaming-first.
- **Inspect** — the Information Discovery Engine reports a ✓/✗ inventory of which canonical fields a file contains, each annotated with the format's capability.
- **Convert** — a single spine, `Native File → Canonical Object → Native File`, driven by a per-format **Capability Matrix** that predicts loss *before* writing. No format ever talks to another format.
- **Recover, explicitly** — the full recovery-scenario catalog: when a target needs a field the source lacks (a lattice, velocities, masses) or can hold only one frame, Xtalate does not guess. You supply a preset choice (`--recover`, e.g. `missing_velocities=maxwell_boltzmann`, `missing_masses=standard_masses`) and it is recorded as an **Assumption**; with no choice, the conversion **refuses** rather than inventing data. Fabrication is exactly what you asked for and nothing more — a Maxwell–Boltzmann draw is emitted raw, with no unrequested "convenience" transforms.
- **Validate, always** — every completed conversion is re-parsed through the ordinary reader and diffed against the expected object under a numeric tolerance profile. There is no switch to skip it. Tolerance is one of the three named profiles (`default` / `strict` / `loose`) **or a custom table** you supply with `--tolerance-profile FILE` (YAML/JSON per-quantity overrides).
- **Round-trip matrix** — beyond identity round-trips, a cross-format **two-hop** (`A→B→Canonical′`) and **three-hop** (`A→B→A`) test suite whose comparable subspace is computed from the Capability Matrix, catching parser/exporter asymmetry.
- **Third-party formats via plugins** — a parser/exporter shipped in a separate installable package is discovered automatically through Python **entry points** (`xtalate.parsers` / `xtalate.exporters`), with no fork or edit to Xtalate; it joins sniffing, Discovery, conversion, and validation on equal footing (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## What v0.5 does *not* do (yet)

- **No Web UI, and no accounts.** The Service is a headless REST API; the Next.js Web UI is v0.6. The v0.5 service runs in **anonymous mode** (optional static API keys only) — there are no user accounts, sessions, or per-user resources, so the account endpoints answer `404 NOT_ENABLED` and a resource is reachable by anyone holding its unguessable id.
- **CIF is read and written, but not every CIF.** A file whose symmetry must be reconstructed from a space-group *symbol* alone is refused rather than guessed at; occupancy is carried under a namespaced key rather than modelled as a first-class canonical field, and only the CIF target writes it back.
- **CLI recovery is still preset-only.** The command line takes choices up front or refuses; the *interactive* pause/resume is a Service feature (`allow_recovery` → `awaiting_recovery`).
- **Pre-1.0, a minor version may break.** The plugin SDK and the REST `/v1` contract are not frozen until v1.0 (risk R12); the canonical schema is still `0.1.0`.

## Install

```bash
pip install xtalate          # once published to PyPI
# or, from a checkout:
pip install -e ".[dev]"
```

Requires Python ≥ 3.11. The only scientific dependency is ASE (for extended XYZ and the ASE `.traj` format); NumPy and pydantic power the canonical model, and PyYAML parses custom tolerance-table files and golden-corpus manifests.

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

Carried-through extras (namespaced, format-specific):
  + user_metadata.custom_per_frame['xyz:comment']
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

Without the `--recover` flags the same command **refuses** (exit code 2) and prints exactly which decisions are needed — a refusal is a first-class, reported outcome, never a silent default.

Exit codes make the CLI CI-native: `0` ok · `2` refused · `3` validation failed · `4` parse error · `5` warnings under `--mode strict` · `1` usage error.

Other commands: `xtalate capabilities [FORMAT]` prints the Capability Matrix; `xtalate validate …` re-validates an existing conversion (full re-parse or tolerance re-thresholding). Any command accepts `--json` to emit the report schema verbatim for piping.

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

A complete, runnable end-to-end example is in [`examples/convert_extxyz_to_poscar.py`](examples/convert_extxyz_to_poscar.py):

```bash
python examples/convert_extxyz_to_poscar.py
```

## Quickstart (HTTP service)

Bring up the full Tier 1 stack — API, worker, PostgreSQL, MinIO, Redis — with one command:

```bash
docker compose up --build --wait
curl -s "http://localhost:8000/v1/health?ready=true"
```

Or run a dependency-free Tier 0 instance (SQLite + local filesystem, jobs executed in-process):

```bash
pip install "xtalate[service]"
python -m backend                       # http://localhost:8000
```

Then upload → convert → download over `/v1`. Conversion is an async job; a refusal comes back as a
**completed HTTP-200 job**, not an error:

```bash
BASE=http://localhost:8000/v1
FILE_ID=$(curl -s -F "file=@in.extxyz" "$BASE/upload" | jq -r .file_id)
JOB=$(curl -s "$BASE/convert" -H 'content-type: application/json' \
  -d "{\"file_id\":\"$FILE_ID\",\"target_format_id\":\"poscar\"}" | jq -r .job_id)
curl -s "$BASE/jobs/$JOB" | jq '.state, .result.conversion_report.status'
CID=$(curl -s "$BASE/jobs/$JOB" | jq -r .result.conversion_id)
curl -s "$BASE/download/$CID" -o POSCAR
```

The full flow — including interactive recovery (`allow_recovery` → pause → resume) and the
reports-outlive-bytes record — is walked through with `curl` in [`docs/API.md` §5](docs/API.md#5-service-http-api),
and the machine-readable contract is the committed [`docs/openapi.json`](docs/openapi.json).

## How it works

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                             ↑        ↓
                         Information Discovery   Capability Matrix
                         Recovery Engine (explicit only) → Validation Engine
```

The **Canonical Object** is the only thing that crosses the parser/exporter boundary — parsers never call other parsers, and the absence convention distinguishes "the source never had this" (`None`) from "the source had it, and the value is zero." The design and its principles are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the library and CLI surface in [`docs/API.md`](docs/API.md); building and extending Xtalate in [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md).

That spine is what makes **adding a format O(1) in the number of formats already present** — a claim now paid three times over. XDATCAR, ASE `.traj`, and CIF each arrived as one parser and one exporter against the Canonical Object plus a row in the Capability Matrix, and each joined sniffing, Discovery, conversion, validation, and the full n×n round-trip matrix without a single edit to any other format. CIF is the strongest evidence, because it is the least like the others: it is the only format whose native coordinates are fractional, the only one carrying symmetry, and the only one that needed a whole expansion stage — and it still cost no format-to-format code, because there is none to write.

Architectural decisions (D1–D71) and MASTER_SPEC are maintained privately. Public commits may
reference decision IDs. If you need the rationale for a particular decision, feel free to open an
issue or contact me.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .    # lint + format
mypy                                     # types (strict)
lint-imports                             # acyclic package layering (P2)
pytest                                   # tests
```

CI runs this matrix on Python 3.11 and 3.13, plus the corpus governance suite over both corpus
roots (manifest schema + license, source hashes, `ATTRIBUTIONS.md` regeneration) and a coverage
ratchet.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The invited path today is
**corpus contributions**: real, licensed sample files that harden the converter. There are two
kinds and they ask different things of you. A **golden** case (`tests/golden/`) asserts what a file
*should* produce and needs an expectation you verified by hand. A **wild** case (`tests/wild/`) is
a real third-party file asserting what it *does* produce — the exact set of issue codes, plus the
composition the file declares for itself — so it needs a triage rather than a derivation, which
makes it much cheaper to add. Both need a manifest and a license; no manifest, no license, no
merge. Parser plugins are welcome too, with the caveat that the plugin SDK is not frozen until
v1.0.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
