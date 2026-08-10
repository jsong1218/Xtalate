# Xtalate v1.0 — Worked-Example Reproduction Procedure

> **What this is.** The Part 10 §6 finish line asks that a **non-author** reproduce Xtalate's worked
> examples on all four surfaces — library, CLI, HTTP service, Web UI — from the *published* docs
> alone. This is that procedure: a self-contained script a stranger can follow start to finish with no
> access to this repository's private specification, test fixtures, or source tree. It builds its own
> inputs, drives each surface exactly as the published docs
> ([`quickstart.md`](../quickstart.md), [`cli.md`](../cli.md), [`API.md`](../API.md),
> [`DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md), and the Web UI) prescribe, and states the result to
> check against.
>
> The examples are one coherent story: **discover** what a file contains, **convert** an ASE
> trajectory to a POSCAR — supplying the frame and lattice the target requires through explicit
> recovery — and read the **validation** that rides with every conversion. Together they exercise the
> whole spine and every promise the product makes: absence is reported, loss is predicted before it
> happens, fabricated data is filed as fabricated, and the output is independently re-checked.
>
> **Status.** The in-session reproduction (all three examples × all four surfaces) was run and passed
> during M38-S3 — see [`DOD_CHECKLIST_v1.0.md` §6 item 4](DOD_CHECKLIST_v1.0.md). This document is the
> ⏳ artifact the maintainer hands to an actual non-author to close the stranger half of the gate.

---

## 0. Prerequisites

- **Python ≥ 3.11.** The library and CLI are pure Python; ASE (a declared dependency) ships with the
  install, so the input-building snippet below needs nothing extra.
- For the **service** surface: **Docker** (Compose v2) *or* the `service` extra for the dependency-free
  Tier-0 run.
- The service `curl` examples parse JSON with **`jq`** (standard on most systems:
  `brew install jq` / `apt install jq`). Every `jq` line below is a convenience — the raw JSON is
  perfectly readable without it if you prefer.

Install the library + CLI:

```bash
pip install xtalate           # library + `xtalate` CLI
xtalate --version             # expect: 1.0.0  (or the release you installed)
```

Everything runs in a scratch directory:

```bash
mkdir xtalate-repro && cd xtalate-repro
```

---

## 1. Build the three inputs

These are the worked-example inputs. They are built here so the procedure is self-contained — no
fixture download, no repository checkout.

**`water_traj.xyz`** — a 2-frame, 3-atom plain-XYZ trajectory with comment lines and *nothing else*
(no cell, velocities, forces, or energies). This is the discovery example.

```bash
cat > water_traj.xyz <<'EOF'
3
frame 0
O   0.000  0.000  0.000
H   0.757  0.586  0.000
H  -0.757  0.586  0.000
3
frame 1
O   0.000  0.000  0.010
H   0.757  0.586  0.010
H  -0.757  0.586  0.010
EOF
```

**`POSCAR.nacl`** — a fractional-coordinate VASP POSCAR (the second discovery example): it *does*
carry a lattice, so it contrasts with the XYZ above.

```bash
cat > POSCAR.nacl <<'EOF'
NaCl primitive test
1.0
  5.640  0.000  0.000
  0.000  5.640  0.000
  0.000  0.000  5.640
Na Cl
1 1
Direct
  0.00 0.00 0.00
  0.50 0.50 0.50
EOF
```

**`relax.traj`** — a 10-frame ASE trajectory of a relaxing water molecule, each frame carrying
`forces` and a `total_energy`, and **no cell** (ASE's default zero cell, which the parser launders to
"absent"). This is the conversion/validation example. Build it with the bundled ASE:

```bash
python - <<'PY'
import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import Trajectory

base = np.array([[0.0, 0.0, 0.0], [0.757, 0.586, 0.0], [-0.757, 0.586, 0.0]])  # O, H, H
with Trajectory("relax.traj", "w") as traj:
    for i in range(10):
        atoms = Atoms("OH2", positions=base + np.array([0, 0, 0.001 * i]))  # no cell
        forces = (0.1 / (i + 1)) * np.array([[0, 0, -1], [0, 0.5, 0.5], [0, -0.5, 0.5]])
        atoms.calc = SinglePointCalculator(atoms, energy=-14.0 + 0.2 * (0.5**i), forces=forces)
        traj.write(atoms)
print("built relax.traj: 10 frames, water, forces + energy, no cell")
PY
```

---

## 2. Surface A — the CLI

Follows [`cli.md`](../cli.md) / [`quickstart.md`](../quickstart.md).

### Example 1 — Discovery (`xtalate inspect`)

```bash
xtalate inspect water_traj.xyz
xtalate inspect POSCAR.nacl --format poscar
```

**Expect** for the XYZ: `atoms.symbols` and `atoms.positions` marked **present** (✓), everything else
— cell, velocities, forces, energies — marked **absent** (✗), and the comment lines carried through as
a namespaced extra `user_metadata.custom_per_frame['xyz:comment']`. Absence is reported, never
defaulted. **Expect** for the POSCAR: additionally `cell.lattice_vectors` and `cell.pbc` present, and
`cell.space_group` absent (POSCAR declares no symmetry; Xtalate carries declared information only).
Exit code `0`.

### Examples 2 + 3 — Conversion with recovery, and its Validation (`xtalate convert`)

The target (POSCAR) stores a single periodic structure, so it needs a frame chosen and a lattice
supplied — both provided explicitly with `--recover`:

```bash
xtalate convert relax.traj --to poscar -o POSCAR \
  --recover frame_selection=last \
  --recover missing_lattice=bounding_box,padding_ang=5.0 \
  --report report.json --validation-report validation.json
```

**Expect** the Conversion Report to show:

- **preserved:** `atoms.symbols`, `atoms.positions`;
- **removed:** `dynamics.forces` and `electronic.total_energy` (POSCAR cannot store them), and
  `atoms.positions` for the nine non-selected frames (single-structure target);
- **supplied:** `cell.lattice_vectors` and `cell.pbc`, each traced to assumption **A2**;
- **assumptions:** **A1** `frame_selection=last` (frame 9 of 10) and **A2** `missing_lattice=bounding_box`
  (padding 5.0 Å) — each described in plain language, the lattice explicitly called a *conversion
  artifact, not simulation data*.

**Expect** the Validation Report `status: passed`, with these nine checks: `atom_count` (pass),
`species_preservation` (pass), `positions_rmsd` (pass), `lattice_consistency` (pass), `frame_count`
(pass), `numeric_field_fidelity` (**skipped** — reported, not omitted), `metadata_preservation`
(pass), `absence_conformance` (pass — the removed paths verified absent in the re-parse), and
`report_consistency` (pass — every supplied path traces to a recorded assumption). Exit code `0`.

---

## 3. Surface B — the library

Follows [`API.md` §2](../API.md#2-library). Save and run:

```python
# repro_lib.py — the library reproduction.
from xtalate.registry import default_registry
from xtalate.conversion import ConversionEngine
from xtalate.discovery import DiscoveryEngine

registry = default_registry()

# Example 1 — Discovery.
with open("water_traj.xyz", "rb") as fh:
    disc = DiscoveryEngine(registry).discover(fh.read(), filename="water_traj.xyz")
present = [f.path for f in disc.fields if f.status == "present"]
print("present:", present)  # expect ['atoms.symbols', 'atoms.positions']

# Examples 2 + 3 — Convert with recovery, and read the validation that rides with it.
with open("relax.traj", "rb") as fh:
    source = registry.get_parser("ase_traj").parse(fh, filename="relax.traj").canonical

result = ConversionEngine(registry).convert(
    source,
    source_format_id="ase_traj",
    target_format_id="poscar",
    recovery_choices={
        "frame_selection": {"choice": "last"},
        "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
    },
)
r = result.report
print("preserved:", [e.path for e in r.preserved])
print("removed  :", [e.path for e in r.removed])
print("supplied :", [(e.path, e.from_assumption) for e in r.supplied])
print("validation:", result.validation.status)
with open("POSCAR", "wb") as fh:
    fh.write(result.output)
```

```bash
python repro_lib.py
```

**Expect** the same accounting as the CLI: `present` = `['atoms.symbols', 'atoms.positions']`;
`preserved` = symbols + positions; `removed` = forces, total_energy, positions; `supplied` =
lattice + pbc (both from `A2`); `validation: passed`.

---

## 4. Surface C — the HTTP service

Follows [`API.md` §5](../API.md#5-service-http-api). Bring up the stack (from a checkout with the
`compose.yaml`, or the published image per [`self-hosting.md`](../self-hosting.md)):

```bash
docker compose up --build --wait
curl -s "http://localhost:8000/v1/health?ready=true"     # expect status:"ok"
```

*(Dependency-free alternative: `pip install "xtalate[service]"` then `python -m backend` — SQLite +
local filesystem, jobs run in-process.)*

Drive the interactive recovery flow — upload, inspect, convert with `allow_recovery` (the job
**pauses**), resume with your choices, download, then read both reports back from the durable record:

```bash
BASE=http://localhost:8000/v1

# 1. Upload — returns a file_id.  (Note the endpoint is /v1/upload.)
FILE_ID=$(curl -s -F "file=@relax.traj" "$BASE/upload" | jq -r .file_id)

# 2. Inspect (Example 1).
JOB=$(curl -s "$BASE/inspect" -H 'content-type: application/json' \
  -d "{\"file_id\":\"$FILE_ID\"}" | jq -r .job_id)
curl -s "$BASE/jobs/$JOB" | jq '.state, [.result.discovery_report.fields[]|select(.status=="present")|.path]'

# 3. Convert asking for interactive recovery — the job pauses at awaiting_recovery.
JOB=$(curl -s "$BASE/convert" -H 'content-type: application/json' -d "{
  \"file_id\": \"$FILE_ID\", \"target_format_id\": \"poscar\",
  \"options\": { \"allow_recovery\": true } }" | jq -r .job_id)
curl -s "$BASE/jobs/$JOB" | jq '.state, [.awaiting_recovery.unresolved_scenarios[].scenario]'

# 4. Resume with your choices (Example 2).
curl -s "$BASE/jobs/$JOB/recovery" -H 'content-type: application/json' -d '{
  "choices": { "frame_selection": { "choice": "last" },
    "missing_lattice": { "choice": "bounding_box", "parameters": { "padding_ang": 5.0 } } } }' > /dev/null
CID=$(curl -s "$BASE/jobs/$JOB" | jq -r .result.conversion_id)

# 5. Download the POSCAR, then read both reports from the durable record (Examples 2 + 3).
curl -s "$BASE/download/$CID" -o out.POSCAR
curl -s "$BASE/conversions/$CID" | jq '.conversion_report.status, .validation_report.status'
```

**Expect:** step 3 shows `"awaiting_recovery"` with the unresolved scenarios
`["frame_selection", "missing_lattice"]` (a paused conversion, never a silent default); the durable
record in step 5 shows `conversion_report.status = "completed"` and `validation_report.status =
"passed"`, with the *same* preserved/removed/supplied/assumptions accounting as the CLI and library —
the assumptions recorded `origin: "user"` because the choices arrived interactively. A conversion the
engine declines would be a *completed* job with `status: "refused"` at HTTP 200, not an error. When
done: `docker compose down -v`.

---

## 5. Surface D — the Web UI

Open `http://localhost:3000` (the same Compose stack serves it). Follows the flow the UI presents.

1. **Landing → "Convert a file."** The landing states the supported formats and this instance's upload
   ceiling.
2. **Upload `relax.traj` and inspect (Example 1).** The inventory marks each canonical field present or
   absent — `atoms.symbols`/`atoms.positions`/`dynamics.forces`/`electronic.total_energy` present, the
   cell absent.
3. **Choose POSCAR as the target and preview the loss.** Before any bytes are written, the preview
   shows forces and energy will be **dropped**, and that a frame and a lattice are **required**.
4. **Decide the recovery (Example 2).** Pick `frame_selection = last` and
   `missing_lattice = bounding_box` with `padding_ang = 5.0`. The UI previews the exact **Assumption**
   sentence it will record — consent and provenance are the same artifact — before you confirm.
5. **Read the record (Examples 2 + 3).** The Conversion Report and Validation Report render
   side by side: dropped fields, the two supplied fields tagged as assumptions, and the validation
   checks all passing. The download sits **below** the report, so the loss is read before the file is
   taken.

**Expect** the record page to show the conversion completed and the validation passed, with the
fabricated lattice shown as an assumption with the same prominence as a dropped field — never buried.

*(This UI journey is also exercised automatically as the `recovery-flagship` Playwright e2e spec —
"upload → convert → pause → decide → preview → record, the trajectory→POSCAR flagship" — which passes
against the running stack.)*

---

## 6. What "reproduced" means

You have reproduced all three worked examples on all four surfaces when, on each, you saw:

- **Discovery** report every field present or absent, defaulting nothing;
- **Conversion** preserve symbols and positions, drop forces/energy/extra-frames *with reasons*, and
  supply the lattice + pbc as **assumptions** (not as preserved data);
- **Validation** pass all nine checks, independently re-parsing the output to confirm the report told
  the truth.

If any published step above did not work as written, that is a documentation defect — report it; under
the v1.0 definition of done it is a release blocker, not a footnote.
