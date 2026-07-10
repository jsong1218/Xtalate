# ChemBridge

[![CI](https://github.com/jsong1218/ChemBridge/actions/workflows/ci.yml/badge.svg)](https://github.com/jsong1218/ChemBridge/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**The trusted translation layer between computational-chemistry file formats — a converter that tells you exactly what it kept, what it lost, and why.**

Every conversion produces a structured **Conversion Report** (what was preserved, dropped, or fabricated, and the reason for each) and an automatic **Validation Report** (the output re-parsed and diffed against the source to prove the report told the truth). The guiding rule is simple: *never silently lose scientific information.* If you diffed the input and output by hand, nothing should surprise you that ChemBridge didn't already tell you about.

## What v0.1 does

- **Formats** (read *and* write): plain **XYZ**, **extended XYZ** (ASE-backed), **POSCAR**, **CONTCAR**.
- **Inspect** — the Information Discovery Engine reports a ✓/✗ inventory of which canonical fields a file contains, each annotated with the format's capability.
- **Convert** — a single spine, `Native File → Canonical Object → Native File`, driven by a per-format **Capability Matrix** that predicts loss *before* writing. No format ever talks to another format.
- **Recover, explicitly** — when a target needs a field the source lacks (e.g. POSCAR requires a lattice) or can hold only one frame, ChemBridge does not guess. You supply a preset choice (`--recover`) and it is recorded as an **Assumption**; with no choice, the conversion **refuses** rather than inventing data.
- **Validate, always** — every completed conversion is re-parsed through the ordinary reader and diffed against the expected object under a numeric tolerance profile. There is no switch to skip it.

## What v0.1 does *not* do (yet)

- **No web service, REST API, or UI.** v0.1 is a pure-Python **library + CLI**. The FastAPI Service and Next.js Web UI are later versions (v0.5 / v0.6) and attach to this core without re-implementing it.
- **Other Phase-1 formats — CIF, XDATCAR, ASE `.traj` — are not yet implemented.** They are v0.2+.
- **Recovery is preset-only.** There is no interactive prompt; the CLI takes choices up front or refuses (interactive recovery is Service/UI machinery).
- **Tolerance profiles are the three named ones** (`default` / `strict` / `loose`). Custom tolerance tables are a later seam.

## Install

```bash
pip install chembridge          # once published to PyPI
# or, from a checkout:
pip install -e ".[dev]"
```

Requires Python ≥ 3.11. The only scientific dependency is ASE (for extended XYZ); NumPy and pydantic power the canonical model.

## Quickstart (CLI)

**Inspect** a file — see what's actually inside it, before converting anything:

```console
$ chembridge inspect water_traj.xyz
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
$ chembridge convert water_traj.xyz --to poscar -o POSCAR \
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

Other commands: `chembridge capabilities [FORMAT]` prints the Capability Matrix; `chembridge validate …` re-validates an existing conversion (full re-parse or tolerance re-thresholding). Any command accepts `--json` to emit the report schema verbatim for piping.

## Quickstart (library)

```python
from chembridge.registry import default_registry
from chembridge.conversion import ConversionEngine

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

## How it works

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                             ↑        ↓
                         Information Discovery   Capability Matrix
                         Recovery Engine (explicit only) → Validation Engine
```

The **Canonical Object** is the only thing that crosses the parser/exporter boundary — parsers never call other parsers, and the absence convention distinguishes "the source never had this" (`None`) from "the source had it, and the value is zero." Full design rationale lives in [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md); build-time decisions in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .    # lint + format
mypy                                     # types (strict)
lint-imports                             # acyclic package layering (P2)
pytest                                   # tests
```

CI runs this matrix on Python 3.11 and 3.13.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
