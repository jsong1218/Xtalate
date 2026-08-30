# Xtalate — API Reference (Library + CLI)

Xtalate is a pure-Python **library** with a thin **CLI** presenter on top. This document is the
reference for both surfaces. For the design and principles behind them, see the
[Architecture Overview](ARCHITECTURE.md); for building and extending Xtalate, the
[Developer Guide](DEVELOPER_GUIDE.md).

> The in-process **library and `xtalate` CLI** are documented first (§1–§4); the **REST Service**
> (v0.5) is §5. The Service exposes the same report models over HTTP without re-implementing the
> core — a thin presenter that embeds the pydantic reports verbatim (no parallel DTOs).

---

## 1. CLI

Install the package (`pip install xtalate`, or `pip install -e ".[dev]"` from a checkout) and the
`xtalate` command becomes available. It has four subcommands.

```
xtalate inspect       Run the Information Discovery Engine (✓/✗ inventory).
xtalate convert       Full pipeline: parse → pre-flight → recovery → export → validate.
xtalate validate      Offline re-parse re-validation, or re-threshold a stored report.
xtalate capabilities  Print the Capability Matrix.
```

Any command accepts `--json` to emit the underlying report schema verbatim (for piping); without
it, output is a human-readable terminal rendering. Global: `xtalate --version`.

### 1.1 `inspect`

```
xtalate inspect FILE [--format FORMAT_ID] [--report PATH] [--json]
```

Reports which canonical fields a file actually contains, each annotated with the format's read
capability — without converting anything. `--format` overrides format sniffing; `--report PATH`
also writes the `DiscoveryReport` JSON to a file.

### 1.2 `convert`

```
xtalate convert FILE --to FORMAT_ID [-o PATH]
                     [--format FORMAT_ID]
                     [--mode permissive|strict]
                     [--recover SCENARIO=CHOICE[,param=value…]]   (repeatable)
                     [--acknowledge-loss] [--acknowledge-parse-warnings]
                     [--tolerance-profile NAME|FILE]
                     [--report PATH] [--validation-report PATH]
                     [--json]
```

Runs the whole pipeline and prints a Conversion Report followed by a Validation Report. `--to` is
required; `-o` writes the converted artifact (without it, the bytes are dumped to stdout in human
mode). Key options:

- **`--recover SCENARIO=CHOICE[,param=value…]`** — supply an explicit recovery preset (repeatable).
  Examples: `--recover frame_selection=last`,
  `--recover missing_lattice=bounding_box,padding_ang=5.0`,
  `--recover missing_velocities=maxwell_boltzmann`, `--recover missing_masses=standard_masses`.
  With no preset for a decision the target requires, the conversion **refuses** rather than guessing.
- **`--mode strict`** — reductive loss and parse warnings must be acknowledged
  (`--acknowledge-loss` / `--acknowledge-parse-warnings`) or the conversion refuses.
- **`--tolerance-profile`** — one of the named profiles `default` / `strict` / `loose`, or a path to
  a custom per-quantity tolerance table (`.json` parsed as JSON, any other extension as YAML).
- **`--report` / `--validation-report`** — also write each report's JSON to a file.

Eligible conversions (an `-o` target, permissive mode, and either no recovery presets or a simple
`first`/`last`/`index` frame selection) are routed through the frame-chunked streaming engine
automatically, so the CLI inherits sub-linear memory on large trajectories. Which path ran is not
observable: the artifact and the report are byte-identical either way.

### 1.3 `validate`

```
# Full offline re-parse re-validation:
xtalate validate --source FILE --output FILE --conversion-report PATH
                 [--tolerance-profile NAME|FILE] [--validation-report PATH] [--json]

# Re-threshold a stored Validation Report under a new profile (no re-parse):
xtalate validate --validation-report REPORT.json --tolerance-profile NAME|FILE [--json]
```

Full re-parse mode reconstructs the expected object from the source file plus the Conversion
Report's write plan, re-parses the output, and diffs. Re-threshold mode re-applies a new tolerance
profile to an already-stored report without re-reading any files. (Offline full re-parse is
unavailable for conversions with recovery-supplied fields, since the fabricated values cannot be
reconstructed from the source; re-threshold the original report instead.)

### 1.4 `capabilities`

```
xtalate capabilities [FORMAT_ID] [--json]
```

Prints the Capability Matrix — what each format can and cannot express, per direction (read/write).
Limit to one format by naming it.

### 1.5 Exit codes

The CLI is CI-native: it signals outcome through the exit code, so you never parse stdout.

| Code | Meaning |
|---|---|
| `0` | OK |
| `1` | usage / internal error |
| `2` | refused (a first-class outcome, not a crash) |
| `3` | validation failed |
| `4` | parse error |
| `5` | passed with warnings under `--mode strict` |

## 2. Library

The library is the CLI without the argument parsing. The entry point is `default_registry()`, which
assembles the built-in parsers/exporters plus any third-party plugins discovered from entry points.

### 2.1 Convert end-to-end

```python
from xtalate.registry import default_registry
from xtalate.conversion import ConversionEngine

registry = default_registry()

# Parse a source file into a Canonical Object.
with open("in.extxyz", "rb") as fh:
    source = registry.get_parser("extxyz").parse(fh, filename="in.extxyz").canonical

# Convert (parse-time recovery, pre-flight, export, and automatic validation all run here).
result = ConversionEngine(registry).convert(
    source,
    source_format_id="extxyz",
    target_format_id="poscar",
)

print(result.report.model_dump_json(indent=2))   # the ConversionReport
print(result.validation.status)                   # "passed" | "passed_with_warnings" | "failed"
with open("POSCAR", "wb") as fh:
    fh.write(result.output)                        # None iff the conversion refused
```

`ConversionEngine.convert(...)` returns a `ConversionResult` with:

- `report: ConversionReport` — always present (a refusal is a completed report with
  `status == "refused"`).
- `output: bytes | None` — the converted bytes; `None` if refused (or if `outputs` carries a
  per-frame set from a `split_all` recovery).
- `canonical_out: CanonicalObject | None` — the write-plan-filtered object handed to the exporter
  (the Validation Engine's expected object); `None` if refused.
- `validation: ValidationReport | None` — exactly one per completed conversion; `None` if refused.
- `outputs: list[bytes] | None` — one file per frame, set only when `frame_selection=split_all`.

Recovery presets are passed as `recovery_choices`, e.g.
`recovery_choices={"missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}}}`.
Other keyword options mirror the CLI flags: `mode`, `acknowledge_loss`,
`acknowledge_parse_warnings`, and `tolerance_profile` (a named profile — `default`/`strict`/`loose`
— or a full custom `ToleranceProfile` / tolerance table; an unknown name or a malformed table is
rejected, never silently ignored).

### 2.2 Inspect (Discovery)

```python
from xtalate.registry import default_registry
from xtalate.discovery import DiscoveryEngine

registry = default_registry()
with open("water.xyz", "rb") as fh:
    report = DiscoveryEngine(registry).discover(fh.read(), filename="water.xyz")
print(report.model_dump_json(indent=2))   # the DiscoveryReport
```

### 2.3 Streaming (large trajectories)

For trajectories that should not be materialized in memory, the Conversion Engine exposes streaming
variants that hold one frame resident and write the target incrementally:

- `ConversionEngine.convert_stream(source, *, source_format_id, target_format_id, output, …)` — a
  frame-chunked conversion writing into an open binary `output` stream.
- `ConversionEngine.convert_stream_select(source, *, frame_selection, output, …)` — the same, for a
  `first`/`last`/`index` frame selection.
- `ConversionEngine.streaming_eligible(source_format_id, target_format_id)` and
  `frame_selection_streaming_eligible(...)` — predicate checks for whether a case can stream.

Streaming changes memory, never truth: the streamed report is proven identical to the materialized
one.

### 2.4 Validation utilities

```python
from xtalate.validation import ValidationEngine, ToleranceProfile, rethreshold
```

- `ValidationEngine(registry).validate(expected=…, output=…, target_format_id=…, conversion_report=…, tolerance=…)`
  — re-parse and diff.
- `ToleranceProfile.named("default"|"strict"|"loose")` and `ToleranceProfile.from_mapping(name, mapping)`
  — build a tolerance profile (the latter from a custom per-quantity table).
- `rethreshold(stored_report, profile)` — re-apply a new tolerance profile to a stored
  `ValidationReport` without re-parsing.

## 3. Report schemas

All three reports are pydantic models. Serialize any of them with `.model_dump(mode="json")` or
`.model_dump_json(indent=2)`; the [Service layer](#5-service-http-api) embeds these same models
verbatim in its HTTP responses (no parallel DTOs).

| Report | What it records |
|---|---|
| **`DiscoveryReport`** | The ✓/✗ inventory of which canonical fields a file contains, each with the format's read capability, plus any namespaced format-specific extras carried through. |
| **`ConversionReport`** | `status` (`completed` / `refused`), and the accounting of every source field: `preserved`, `removed`, `supplied` (with the `assumptions` that produced each fabricated value), and `warnings`. The completeness invariant guarantees every source field appears in exactly one of these. |
| **`ValidationReport`** | `status` (`passed` / `passed_with_warnings` / `failed`), the tolerance profile used, and the per-check results (atom count, species preservation, positions RMSD, lattice consistency, frame count, numeric field fidelity, metadata preservation, absence conformance, report consistency). |

## 4. Supported formats

Read **and** write: `xyz`, `extxyz`, `poscar`, `contcar`, `xdatcar`, `ase_traj`, `cif`,
`lammps_dump`, `lammps_data`, `qe_pw_in`, `ase_db`, and `deepmd_npy` (a directory format —
see the [Developer Guide](DEVELOPER_GUIDE.md) for its `-o DIR` write surface). Read-only /
parser-only sources: `vasprun` (VASP `vasprun.xml`), `outcar` (VASP `OUTCAR`), and `qe_pw_out`
(pw.x output); they are valid conversion sources but never targets. A **dataset is aggregation,
not a new model**: a multi-row `ase_db` or a multi-frame directory fans out under
`convert --batch`, and `assemble` builds one container (extXYZ, `.db`, DeePMD systems) from N
sources — every per-file report is embedded verbatim and tallies are counts, never
restatements. Third-party formats registered via entry points (see the [Developer
Guide](DEVELOPER_GUIDE.md)) appear here on equal footing — `xtalate capabilities` always reflects
the live set.

## 5. Service (HTTP API)

The same engine is exposed over HTTP under `/v1`. The API is a thin presenter over the library — it
contains no scientific logic, and every response embeds the pydantic report models **verbatim** (the
same schemas as §3, no parallel DTOs). Two rules run through the whole surface:

- **A refused conversion is not an error.** A conversion the engine declines is a *completed* job
  whose `ConversionReport.status == "refused"`, returned as **HTTP 200** — never a 4xx.
- **Long operations are async jobs.** `inspect` / `convert` / `validate` return a job; you poll
  `GET /v1/jobs/{job_id}` until it reaches `completed` (or `awaiting_recovery`, if you opted into
  interactive recovery). The machine-readable contract is the committed
  [`openapi.json`](openapi.json) artifact.

### 5.1 Run it locally

One command brings up the Tier 1 stack (API + worker + PostgreSQL + MinIO + Redis):

```bash
docker compose up --build --wait
# readiness — green only once migrations ran and the DB + object store answer:
curl -s "http://localhost:8000/v1/health?ready=true"
```

For a dependency-free Tier 0 run (SQLite + local filesystem, jobs executed in-process), install the
service extra and run the app directly — no database or object store to stand up:

```bash
pip install "xtalate[service]"
python -m backend            # serves on http://localhost:8000
```

### 5.2 The full flow with `curl`

Upload a file, convert it interactively (the two-frame molecular input needs both a frame picked and
a lattice supplied for a periodic POSCAR target — the worked example of the recovery workflow),
resume with your choices, then download the output.

```bash
BASE=http://localhost:8000/v1

# 1. Upload — returns a file_id.
FILE_ID=$(curl -s -F "file=@traj.xyz" "$BASE/upload" | jq -r .file_id)

# 2. Inspect — the Discovery Report (✓/✗ per canonical field). Poll the job to completed.
JOB=$(curl -s "$BASE/inspect" -H 'content-type: application/json' \
  -d "{\"file_id\":\"$FILE_ID\"}" | jq -r .job_id)
curl -s "$BASE/jobs/$JOB" | jq .result.discovery_report

# 3. Convert to POSCAR asking for interactive recovery — the job PAUSES at awaiting_recovery
#    with the computed options for each unresolved scenario.
JOB=$(curl -s "$BASE/convert" -H 'content-type: application/json' -d "{
  \"file_id\": \"$FILE_ID\",
  \"target_format_id\": \"poscar\",
  \"options\": { \"allow_recovery\": true }
}" | jq -r .job_id)
curl -s "$BASE/jobs/$JOB" | jq '.state, .awaiting_recovery.unresolved_scenarios[].scenario'

# 4. Resume with your choices — every choice is recorded as an Assumption in the report.
curl -s "$BASE/jobs/$JOB/recovery" -H 'content-type: application/json' -d '{
  "choices": {
    "frame_selection": { "choice": "last" },
    "missing_lattice": { "choice": "bounding_box", "parameters": { "padding_ang": 5.0 } }
  }
}' > /dev/null
CID=$(curl -s "$BASE/jobs/$JOB" | jq -r .result.conversion_id)

# 5. Download the converted POSCAR (streamed through the API, never a presigned URL).
curl -s "$BASE/download/$CID" -o out.POSCAR

# The durable record serves BOTH reports back verbatim — even after the bytes expire.
curl -s "$BASE/conversions/$CID" | jq '.conversion_report.status, .validation_report.status'
```

Before you resume, you can **preview the exact Assumptions your choices would record** — without
advancing the job — by POSTing the same `{ choices }` body to
`/v1/jobs/{job_id}/recovery/preview`. It returns `{ previews: [{ scenario, choice, parameters,
description }…], unresolved: [<scenario>…] }`, where each `description` is byte-identical to the
Assumption the resume will write, because the preview runs the engine's real apply path and returns
its sentence verbatim (the browser cannot reproduce it — that is the point). Recovery is
all-or-nothing: an incomplete choice set returns no `previews` and names the scenarios still
`unresolved` instead. The preview writes nothing, enqueues nothing, and leaves the job paused and
answerable; it shares the resume's guards (`404`, `409 JOB_NOT_AWAITING_RECOVERY`,
`422 INVALID_RECOVERY_CHOICE`). This is how the Web UI shows the record you are about to create
before you confirm it — consent and provenance are the same artifact.

The `options` object also accepts `tolerance_profile` — a named profile (`default`/`strict`/`loose`)
or a full custom tolerance table; an unknown name or a malformed table is refused at submit as
`400 MALFORMED_REQUEST` carrying the library's own reason, before a job exists (D93).

Supplying the same `recovery_choices` in the initial `convert` request (instead of
`allow_recovery`) skips the pause and completes in one call — the preset path and the interactive
path produce byte-equivalent reports. Read the advertised limits (`GET /v1/limits`) before you hit
them: an oversized upload is `413`, a rate burst is `429` with `Retry-After`, and — on an instance
configured with a static API key — a keyless mutating request is `401`.

### 5.3 The `/v1` contract and how it evolves

As of the v1.0 contract freeze, the `/v1` surface is **frozen for the 1.x series**. Three things are
the contract, and they are the same three the service ships as machine-readable artifacts:

- the **endpoint set** — the paths and methods enumerated above (`upload`, `inspect`, `convert`,
  `validate`, `batch/convert` (v1.5), `jobs/{id}` and its `recovery` / `recovery/preview` /
  `cancel` sub-resources, `conversions/{id}`, `download/{id}`, `history`,
  `capabilities[/{format_id}]`, `limits`, `health`, plus the v1.6 additive **read-only geometry**
  routes `files/{id}/geometry` and `conversions/{id}/geometry` (below));
- the **response envelopes** — the pydantic report models of §3, embedded verbatim, and the single
  error envelope `{ error: { code, message, details, request_id, documentation_url } }`; and
- the **error-code set** — the stable machine strings each non-2xx response carries, cataloged in
  [`error_codes.json`](error_codes.json) with a human reference in [`errors.md`](errors.md).

[`docs/openapi.json`](openapi.json) is the **versioned, machine-readable form of this contract**. It
is generated deterministically from the assembled app (`python -m backend.openapi`), source-pinned so
two checkouts produce byte-identical output, and diff-guarded in CI — a route added, a field renamed,
or a status code changed fails the build until the artifact is regenerated on purpose. It is
published as a release artifact, so each release carries the exact `/v1` schema it shipped.

The surface evolves under an **additive-only policy** (Part 6 §7), so a client written against 1.x
keeps working across the series:

- **Path-prefix versioning.** The version lives in the path (`/v1`). A change that would break the
  frozen endpoints, envelopes, or codes waits for a new prefix (`/v2`); it is never slipped into
  `/v1`.
- **New capability arrives as *values*, not new endpoints.** A new format or a new recovery scenario
  is a new *value* in an existing request or response field (a `format_id`, a scenario name), so it
  needs no new route — `GET /v1/capabilities` and the report bodies simply carry more. Third-party
  plugin formats appear on this surface with no API change at all.
- **Additive fields are non-breaking.** New optional request fields and new response fields may be
  added within 1.x; existing fields are not removed, renamed, or repurposed, and an existing error
  code is never given a new meaning (new codes may be *added* to the set).

### 5.4 Batch conversion (`POST /v1/batch/convert`) — an additive job kind (v1.5 M58)

The batch endpoint is the HTTP form of the library's `run_batch` contract — the API reproduces it,
never re-implements it (the same `BatchTallies`/`LabelPresence` and verbatim-embedding rules). It is
an **additive job kind**: the `/v1` endpoints, envelopes, and codes above are unchanged, and a
client that never calls it keeps working.

```bash
# Upload the files first (each is an ordinary upload):
F1=$(curl -s -F "file=@run1/vasprun.xml" "$BASE/upload" | jq -r .file_id)
F2=$(curl -s -F "file=@run2/pw.out" "$BASE/upload" | jq -r .file_id)
# Submit the batch: ordered file_ids + one target + shared options.
JOB=$(curl -s "$BASE/batch/convert" -H 'content-type: application/json' -d "{
  \"file_ids\": [\"$F1\", \"$F2\"],
  \"target_format_id\": \"extxyz\"
}" | jq -r .job_id)
# Poll the parent; its result is the aggregate (tallies + per-file entries embedding each
# child's reports verbatim) and its `children` projection names each child job:
curl -s "$BASE/jobs/$JOB" | jq '.state, .result.tallies, .children'
# Each child is an ordinary job — GET /v1/jobs/{child_id} is its own full record.
```

Semantics worth knowing before you call it:

- **One target, shared options.** The request is `{ file_ids: [...], target_format_id, options }`
  with an optional per-file `overrides` list whose fields **replace** the shared value (an unset
  field inherits; `recovery_choices` replace, never merge — the library `SourceOverride`
  semantics). At least one `file_id` is required (`422 EMPTY_BATCH`); an empty list is the only
  batch-specific refusal.
- **Fan-out to ordinary child jobs.** The parent creates N ordinary `kind="convert"` child jobs,
  each a navigable record with its own pause, refusal, expiry, and cancellation — exactly as if
  submitted alone. A rejected submit leaves no orphans: children are created by the parent's
  dispatch, so a request that fails validation creates none.
- **Per-file consent stays per-file.** A child that pauses at `awaiting_recovery` leaves the
  parent **honestly non-terminal at the same state with no recovery block of its own** — the batch
  never answers a recovery question wholesale, and resuming the parent with choices is
  `422 INVALID_RECOVERY_CHOICE`. Answer the child on its own record; once every child is
  terminal, the parent re-drives itself lazily on the next `GET /v1/jobs/{id}` poll and completes.
- **The aggregate is a container, never a digest.** `result.entries[]` embeds each child's
  `ConversionReport`/`ValidationReport` verbatim (byte-identical to the child's own record), and
  `result.tallies` are counts (total/converted/refused/failed + `label_presence`) — no merged
  assumptions, no "top losses" summary. A cancelled child reports `failed` with code
  `JOB_CANCELLED`; a child whose pause expired resolves as a `RECOVERY_REQUIRED` refusal, never a
  silent default.
- **Navigable in every state.** The envelope carries an additive `children: [{ job_id, file_id,
  state }…]` projection so a client (or the Web UI) can reach each child's record whether the
  batch is running, paused, or complete.

The committed [`openapi.json`](openapi.json) is regenerated (`python -m backend.openapi`) and
contains the exact request/response schema; `EMPTY_BATCH` and `JOB_CANCELLED` are cataloged in
[`error_codes.json`](error_codes.json).


### 5.5 Read-only geometry endpoints (`GET /v1/files/{id}/geometry`, `GET /v1/conversions/{id}/geometry`) — an additive read surface (v1.6 M59)

Two **additive** `GET` routes expose the canonical geometry the viewer renders, as a wire projection
of the Canonical Object — never a second canonical artifact and never a hidden export:

- `GET /v1/files/{file_id}/geometry` — an uploaded file's own geometry;
- `GET /v1/conversions/{conversion_id}/geometry?side=source|output` — a conversion's source or
  re-parsed output geometry (the two objects the Validation Engine diffed).

Both take a half-open, 0-based `?frames=start:end` window (default `0:1`, a single structure) and
return `species` (one symbol per atom), an optional per-frame `cell` (a `(3, 3)` lattice; `null`
when the source carried none — absence renders as absence, P3), per-frame `positions` as nested
lists, `frame_index_base` (the window's absolute first index) and `frame_count` (the whole object's
total). The endpoints ride the existing streaming engine behind a byte-bounded server-side cache —
never materializing a whole trajectory. **Geometry expires with the bytes**: once the underlying
bytes are gone the route answers `410 FILE_EXPIRED` / `OUTPUT_EXPIRED`, while the conversion record
and its reports remain readable (reports outlive bytes). A malformed or reversed range is
`400 INVALID_FRAME_RANGE`. **No bonds**: the Canonical Model holds no bonds, so the projection
carries none — a coordination bond is a display heuristic (D234), never file content and never served
here. This surface changes **no** library/CLI surface; it is the Web UI viewer's read path only.
