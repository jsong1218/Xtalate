# Xtalate

[![CI](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml/badge.svg)](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)](CHANGELOG.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**A loss-aware converter for computational-chemistry file formats — it tells you exactly what each conversion kept, dropped, or had to fabricate, and proves it.**

Every conversion produces a **Conversion Report** (what was preserved, dropped, or supplied — with a reason for each) and a **Validation Report** (the output re-parsed and diffed against the source). The rule behind the whole tool: *never silently lose scientific information.* If you diffed the input and output by hand, nothing should surprise you that Xtalate didn't already flag.

## Install

```bash
pip install xtalate
```

Python ≥ 3.11. ASE is the only scientific dependency.

## Quickstart

See what's inside a file before touching it:

```bash
xtalate inspect water_traj.xyz
```

Convert it. This XYZ trajectory has no lattice, and POSCAR needs one structure *and* a cell — so you supply those two choices explicitly, and each is recorded as an Assumption:

```bash
xtalate convert water_traj.xyz --to poscar -o POSCAR \
    --recover frame_selection=last \
    --recover missing_lattice=bounding_box,padding_ang=5.0
```

```
Conversion Report  [completed]
  xyz → poscar
  preserved: atoms.symbols, atoms.positions
  supplied:  cell.lattice_vectors, cell.pbc
  assumptions:
    ~ A1 frame_selection=last          frame 1 of 2 retained
    ~ A2 missing_lattice=bounding_box   axis-aligned box + 5.0 Å padding

Validation Report  [passed]  (tolerance: default)
  ✓ atom_count · ✓ species_preservation · ✓ positions_rmsd · ✓ lattice_consistency …
```

Leave out the `--recover` flags and the command **refuses**, printing the exact decisions it needs — a refusal is a reported outcome, never a silent default. Exit codes make it CI-native (`0` ok · `2` refused · `3` validation failed · `4` parse error · `5` strict-mode warnings · `1` usage), and `--json` on any command emits the report schema verbatim.

Full [CLI reference](docs/cli.md) · [library example](examples/convert_extxyz_to_poscar.py).

## Supported formats

| Format | Read | Write | Notes |
|---|:---:|:---:|---|
| XYZ | ✓ | ✓ | Plain coordinates |
| extended XYZ | ✓ | ✓ | ASE-backed; MLIP labels (energy, forces, stress) |
| POSCAR / CONTCAR | ✓ | ✓ | VASP structure; CONTCAR keeps the velocity block |
| XDATCAR | ✓ | ✓ | VASP trajectory |
| ASE `.traj` | ✓ | ✓ | |
| CIF | ✓ | ✓ | Symmetry from declared operations; site occupancy is first-class |
| LAMMPS dump | ✓ | ✓ | MD trajectory; unit system resolved explicitly |
| LAMMPS data | ✓ | ✓ | Input / restart; atom style resolved explicitly |
| Quantum ESPRESSO pw.x input | ✓ | ✓ | Namelists + cards |
| ASE `.db` | ✓ | ✓ | Multi-structure dataset |
| DeePMD-kit npy | ✓ | ✓ | Directory system; MLIP training layout |
| vasprun.xml | ✓ | — | VASP output (source only) |
| OUTCAR | ✓ | — | VASP output; per-atom magnetic moments |
| Quantum ESPRESSO pw.x output | ✓ | — | QE output (source only) |

Read-only formats are conversion *sources*, never targets — a code's output is never something Xtalate writes back. In-memory adapters also translate pymatgen `Structure`/`Molecule` objects (`pip install "xtalate[pymatgen]"`), and **CP2K** is available through the community-plugin seam. Any pair of read+write formats converts; the nightly suite runs the full n×n matrix.

These formats close the MLIP data loop end to end — **relabel** production frames with DFT (`OUTCAR`/`vasprun.xml`/QE output → extended XYZ), **assemble** them into a dataset (`ase_db`, `deepmd_npy`), and **deploy** back to an engine (LAMMPS) — every arrow a reported, validated conversion.

## What every conversion gives you

- **Inspect first.** A ✓/✗ inventory of which canonical fields a file actually holds, each annotated with the format's capability — no conversion needed.
- **Loss predicted before writing.** A per-format Capability Matrix tells the exporter what the target can hold *before* it writes (**P5**).
- **Recovery is explicit, never guessed.** When a target needs a field the source lacks, you choose a preset and it becomes an Assumption; with no choice, the conversion refuses rather than invent data (**P4**).
- **Validation is not optional.** Every conversion is re-parsed and diffed against the source under a tolerance profile (`default` / `strict` / `loose`, or a custom table). There is no switch to skip it.
- **Absence is information (P3).** The model distinguishes "the source never had this" (`None`) from "the source had it, and the value is zero." Parsers never default an absent field.
- **Scales to large trajectories.** A frame-chunked streaming core keeps memory sub-linear in frame count; a 10⁴-frame XDATCAR streams at roughly constant memory and yields a byte-identical report.
- **Extensible by plugins.** A parser/exporter in a separate package is discovered through Python entry points (`xtalate.parsers` / `xtalate.exporters`) with no fork or edit. First-party formats hold no privileged API.

## Beyond the CLI

The same engine drives four surfaces; the scientific logic lives in the engine and nowhere else.

**Library:**

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
```

**HTTP service** — a FastAPI app exposing the engine as async jobs under `/v1`:

```bash
pip install "xtalate[service]"
python -m backend                       # http://localhost:8000
# or the full stack (API, worker, Postgres, MinIO, Redis):
docker compose up --build --wait
```

A refusal comes back as a completed HTTP-200 job, not an error; reports outlive the bytes they describe. The `curl` walkthrough is in [`docs/API.md`](docs/API.md), and the machine-readable contract is [`docs/openapi.json`](docs/openapi.json).

**Web UI** — a Next.js front end over `/v1` that walks upload → inspect → convert → recover → download, rendering the engine's reports verbatim (no scientific logic of its own). Self-hosting is the primary deployment; see the [self-hosting guide](docs/self-hosting.md).

**Batch** — `xtalate convert --batch manifest.yaml -o out/` (and `POST /v1/batch/convert`) converts a whole directory into one record: each file's reports embedded verbatim, tallies on top, one file's failure never aborting the rest. Selection, splitting, and deduplication are deliberately out of scope — curation is a scientific judgment, conversion is a translation.

## How it works

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                             ↑        ↓
                         Information Discovery   Capability Matrix
                         Recovery Engine (explicit only) → Validation Engine
```

The **Canonical Object** is the only thing that crosses the parser/exporter boundary — no parser calls another parser, and no conversion takes a format-to-format shortcut (**P2**). That single spine makes adding a format O(1) in the number already present: each new format is one parser, one exporter, and a Capability Matrix row, joining sniffing, discovery, conversion, and validation without touching any other format.

Design and principles: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · library/CLI surface: [`docs/API.md`](docs/API.md) · building and extending: [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md).

## Versioning

Xtalate follows [Semantic Versioning](https://semver.org/). Within a major series a named public surface — the canonical schema, the report schemas, the plugin SDK, the `/v1` REST surface, and the documented CLI — evolves **additively only**: new formats, scenarios, and optional fields arrive with safe defaults, and nothing already documented is removed or given a new meaning. The `_`-prefixed internal surface is not part of the contract.

The product version and the on-the-wire `schema_version` move on separate axes: the schema version bumps only when the model changes, and always behind a real migration that carries older stored objects forward with a recorded `migrate` step — never silently.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .    # lint + format
mypy                                     # types (strict)
lint-imports                             # acyclic package layering (P2)
pytest                                   # tests
```

CI runs on Python 3.11 and 3.13, plus corpus governance over both corpus roots and a coverage ratchet.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The invited path is **corpus contributions**: real, licensed sample files that harden the converter. A **golden** case (`tests/golden/`) asserts what a file *should* produce; a **wild** case (`tests/wild/`) is a real third-party file asserting what it *does* produce. Both need a manifest and a license — no manifest, no license, no merge. Parser plugins are welcome too; the plugin SDK is a stable contract.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
