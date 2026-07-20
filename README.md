# Xtalate

[![CI](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml/badge.svg)](https://github.com/jsong1218/Xtalate/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

**The trusted translation layer between computational-chemistry file formats — a converter that tells you exactly what it kept, what it lost, and why.**

Every conversion produces a structured **Conversion Report** (what was preserved, dropped, or fabricated, and the reason for each) and an automatic **Validation Report** (the output re-parsed and diffed against the source to prove the report told the truth). The guiding rule is simple: *never silently lose scientific information.* If you diffed the input and output by hand, nothing should surprise you that Xtalate didn't already tell you about.

## What v0.3 does

- **Formats** (read *and* write): plain **XYZ**, **extended XYZ** (ASE-backed), **POSCAR**, **CONTCAR** — including the POSCAR/CONTCAR **velocity block** (Cartesian + Direct) — **XDATCAR**, and the **ASE `.traj`** format. That's **six of the seven Phase-1 formats**; CIF is the last, landing in v0.4.
- **Scales to large trajectories** — a frame-chunked streaming core makes pipeline memory **sub-linear in the number of frames**: `convert` streams a 10⁴-configuration XDATCAR at roughly constant memory and produces a Conversion Report **byte-identical** to the materialized path. XDATCAR and ASE `.traj` are streaming-first.
- **Inspect** — the Information Discovery Engine reports a ✓/✗ inventory of which canonical fields a file contains, each annotated with the format's capability.
- **Convert** — a single spine, `Native File → Canonical Object → Native File`, driven by a per-format **Capability Matrix** that predicts loss *before* writing. No format ever talks to another format.
- **Recover, explicitly** — the full recovery-scenario catalog: when a target needs a field the source lacks (a lattice, velocities, masses) or can hold only one frame, Xtalate does not guess. You supply a preset choice (`--recover`, e.g. `missing_velocities=maxwell_boltzmann`, `missing_masses=standard_masses`) and it is recorded as an **Assumption**; with no choice, the conversion **refuses** rather than inventing data. Fabrication is exactly what you asked for and nothing more — a Maxwell–Boltzmann draw is emitted raw, with no unrequested "convenience" transforms.
- **Validate, always** — every completed conversion is re-parsed through the ordinary reader and diffed against the expected object under a numeric tolerance profile. There is no switch to skip it. Tolerance is one of the three named profiles (`default` / `strict` / `loose`) **or a custom table** you supply with `--tolerance-profile FILE` (YAML/JSON per-quantity overrides).
- **Round-trip matrix** — beyond identity round-trips, a cross-format **two-hop** (`A→B→Canonical′`) and **three-hop** (`A→B→A`) test suite whose comparable subspace is computed from the Capability Matrix, catching parser/exporter asymmetry.
- **Third-party formats via plugins** — a parser/exporter shipped in a separate installable package is discovered automatically through Python **entry points** (`xtalate.parsers` / `xtalate.exporters`), with no fork or edit to Xtalate; it joins sniffing, Discovery, conversion, and validation on equal footing (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## What v0.3 does *not* do (yet)

- **No web service, REST API, or UI.** Xtalate is a pure-Python **library + CLI**. The FastAPI Service and Next.js Web UI are later versions (v0.5 / v0.6) and attach to this core without re-implementing it.
- **CIF — the seventh and last Phase-1 format — is not yet implemented.** It lands in v0.4.
- **Recovery is preset-only.** There is no interactive prompt; the CLI takes choices up front or refuses (interactive recovery is Service/UI machinery).
- **Pre-1.0, a minor version may break.** The plugin SDK is not frozen until v1.0 (risk R12); the canonical schema is still `0.1.0`.

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

## How it works

```
Native File → Format Sniffer → Parser → Canonical Object → Exporter → Target Format
                                             ↑        ↓
                         Information Discovery   Capability Matrix
                         Recovery Engine (explicit only) → Validation Engine
```

The **Canonical Object** is the only thing that crosses the parser/exporter boundary — parsers never call other parsers, and the absence convention distinguishes "the source never had this" (`None`) from "the source had it, and the value is zero." The design and its principles are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the library and CLI surface in [`docs/API.md`](docs/API.md); building and extending Xtalate in [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md).

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .    # lint + format
mypy                                     # types (strict)
lint-imports                             # acyclic package layering (P2)
pytest                                   # tests
```

CI runs this matrix on Python 3.11 and 3.13, plus the golden-corpus governance suite
(manifest schema + license, source hashes, `ATTRIBUTIONS.md` regeneration) and a coverage
ratchet.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The invited path today is
**golden-corpus contributions**: real, licensed sample files that harden the converter. Parser
plugins are welcome too, with the caveat that the plugin SDK is not frozen until v1.0.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
