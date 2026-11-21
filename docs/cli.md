# CLI reference

The `xtalate` command is a thin presenter over the library — the same engine the HTTP service uses.
It has five subcommands:

```
xtalate inspect       Run the Information Discovery Engine (✓/✗ inventory).
xtalate convert       Full pipeline: parse → pre-flight → recovery → export → validate.
xtalate validate      Offline re-parse re-validation, or re-threshold a stored report.
xtalate capabilities  Print the Capability Matrix.
xtalate scenarios     Print the recovery-scenario catalog (the choices `--recover` accepts).
```

Global:

```
xtalate --version     Print the version and exit.
```

Every subcommand accepts `-q`/`--quiet` (suppress status output and progress; errors, exit codes and
`--json` remain) and `-v`/`--verbose` (print pipeline stages to stderr; it affects `convert` only).

Every command signals its outcome through the exit code (see [Exit codes](#exit-codes)) and can emit
machine-readable JSON with `--json`.

As of the v1.0 contract freeze, the CLI surface documented here — the five subcommands, their flags,
the `--json` convention, and the exit-code ladder below — is **frozen for the 1.x series**. Within
1.x it evolves additively only: new flags and new formats may appear, but a documented flag is not
removed, renamed, or given a new meaning, and the exit codes keep the meanings tabled here.

## inspect

Report what a file contains without converting it — each canonical field marked present or absent
(**P3**: absence is information).

```
xtalate inspect FILE [--format FORMAT_ID] [--report PATH] [--json]
```

| Flag | Meaning |
|---|---|
| `FILE` | The file to inspect. |
| `--format FORMAT_ID` | Override format sniffing (use when the extension is ambiguous or wrong). |
| `--report PATH` | Write the `DiscoveryReport` JSON to `PATH`. |
| `--json` | Print the `DiscoveryReport` JSON to stdout. |

## convert

Run the full pipeline and write the converted file plus its Conversion Report.

```
xtalate convert FILE… --to FORMAT_ID [-o PATH] [--format|--from FORMAT_ID]
                [--mode permissive|strict]
                [--recover "SCENARIO=CHOICE[,param=value…]"]…
                [--repair OPERATION[,param=value…]]… [--frames START:STOP[:STEP]|N]
                [--dry-run]
                [--acknowledge-loss] [--acknowledge-parse-warnings]
                [--tolerance-profile NAME|FILE]
                [--report PATH] [--validation-report PATH] [--json] [--no-bell]
```

| Flag | Meaning |
|---|---|
| `FILE…` | Source file(s), glob(s) or a directory of files to convert into `-o DIR`; `-` reads stdin (needs `--from`). List all inputs before the options. Omit with `--batch`. |
| `--to FORMAT_ID` | Target format. Required unless it can be inferred from the `-o` extension (see below); never inferred from `-o -`. |
| `-o`, `--output PATH` | Write the converted file to `PATH` (a directory when converting several inputs). `-` writes the result to stdout (status text goes to stderr; a trajectory is then held in memory). |
| `--format FORMAT_ID`, `--from FORMAT_ID` | Override source-format sniffing (`--from` is an alias). |
| `--repair OPERATION[,param=value…]` | Apply a repair operation before export. Repeatable; applied in the order given. Operations: `wrap_into_cell` (no parameters); `center` (`reference=centroid\|cell_center`, `target=origin\|cell_center`); `deduplicate` (`distance_threshold=ANGSTROM`); `species_reorder` (optional `permutation=…`); `select_frames` (`start=`, `stop=`, `step=`: keep a Python-slice subset of frames). An explicit-coordinate `[x, y, z]` center target is not supported on the CLI yet. |
| `--frames START:STOP[:STEP]\|N` | Keep a Python-slice subset of frames (e.g. `0:100:5`, `::2`, `--frames=-10:`); a bare integer `N` keeps only frame `N` (negative counts from the end). Same as `--repair select_frames`. Write a leading-minus value with `=` (`--frames=-1`). A range that selects no frames is refused (usage error), never an empty file. |
| `--dry-run` | Parse, apply repairs and pre-flight only; write nothing. Exit `0` if the conversion would run without a recovery choice, `2` if it needs one or would be refused. In `--mode strict` the acknowledgement gates are evaluated (pass `--acknowledge-loss` / `--acknowledge-parse-warnings` to see the run as acknowledged); strict-mode refusals are predicted from predicted loss and parse warnings only, not from loss that appears at recovery time. When nothing needs a recovery choice, a value the target format cannot state (the exporter's `UNREPRESENTABLE_VALUE` refusal, such as per-axis periodicity written to `deepmd_npy`) is predicted too; such a refusal that would only arise after a recovery choice is applied cannot be predicted. Cannot be combined with `--recover` (a dry run reports the choices a real run would ask for) or with `--validation-report` (it runs no validation). |
| `--mode permissive\|strict` | `strict` refuses on any predicted loss; `permissive` (default) reports it. |
| `--recover "SCENARIO=CHOICE[,param=value…]"` | Preset a recovery choice for a required-but-missing field. Repeatable. Every choice is recorded as an Assumption. |
| `--acknowledge-loss` | Proceed past reported loss non-interactively. |
| `--acknowledge-parse-warnings` | Proceed past parse warnings non-interactively. |
| `--tolerance-profile NAME\|FILE` | `default`, `strict`, `loose`, or a custom tolerance table (YAML/JSON) for validation. |
| `--report PATH` | Write the `ConversionReport` JSON. |
| `--validation-report PATH` | Write the `ValidationReport` JSON. |
| `--json` | Print both reports as one JSON object. |
| `--no-bell` | Do not ring the terminal bell when the conversion finishes. |
| `-q`, `--quiet` / `-v`, `--verbose` | Suppress status output and progress / print pipeline stages to stderr (mutually exclusive). |

Refusals print the exact `--recover scenario=choice` lines needed, ready to copy (a choice that takes
free text, such as `species_map`, is printed quoted: `--recover "missing_species=species_map,species=1:Si 2:O"`).
`xtalate scenarios` lists every scenario and its choices.

**Target inference.** When `--to` is omitted, the target is inferred from the `-o` extension if exactly
one registered format claims it (`xtalate convert relax.vasp -o relax.cif`); an ambiguous extension such
as `.xyz` still needs `--to`, and `-o -` never infers one.

**Several inputs, directories, stdin.** Pass several files, globs or a directory and give `-o DIR`
(with `--to`): each file converts independently into the directory. A directory that is not itself a
recognised source directory (such as a DeePMD system) fans out per file; a file of unknown format
exits `4` with a `parse error [UNKNOWN_FORMAT]` summary line. The process exit code is the worst
per-file outcome (highest wins). Each output is named `<input stem>.<target extension>`. A planned
output that would be one of the inputs themselves (for example `xtalate convert in/ -o in --to
extxyz` with `in/foo.extxyz` among the inputs) is refused as a usage error (exit `1`) before anything
is written; two inputs that would write the same output name are refused the same way. Any other
file already in `-o DIR` under an output's name is overwritten, as a single `-o PATH` is. Under
`--dry-run` each summary line reads `would complete`, `needs recovery` or `would refuse`. `-` reads the source from stdin and needs `--from`;
`-o -` writes the converted file to stdout.

```bash
xtalate convert runs/*.xyz --to extxyz -o out/
cat POSCAR | xtalate convert - --from poscar --to cif -o -
xtalate convert md.xyz --to extxyz -o subset.extxyz --frames 0:100:5
xtalate convert md.traj --to extxyz --dry-run
```

**Progress.** For streamed conversions the CLI prints a frame-progress line to **stderr**, only when
stderr is a terminal; `--quiet` suppresses it.

A conversion that would need data the source lacks does not guess — it refuses unless you supply the
value with `--recover`. See the [API reference](./api#12-convert) for the recovery scenarios and
their choices.

**The completion bell (v1.1 M39-S4).** When `xtalate convert` finishes — with a converted file *or*
a refusal — the CLI rings the terminal bell (`\a`) on **stderr**, but only when stderr is a terminal
(a piped or redirected stream never receives control bytes). Opt out per-invocation with `--no-bell`,
or globally by setting `XTALATE_NO_BELL` (any non-empty value).

### Batch conversion (`--batch`) — v1.5 M54

Convert many sources through one manifest, run as the **ordinary single-file path per file**, and
aggregated into one `BatchReport` (with per-file `ConversionReport`/`ValidationReport` embedded
verbatim). The manifest carries the target and the shared settings, so passing them on the command
line (`--mode`/`--recover`/`--tolerance-profile`/the acknowledge flags) is a usage error in batch
mode — the manifest wins by design.

```
xtalate convert --batch MANIFEST.yaml -o PATH [--fail-fast] [--json] [--no-bell]
```

| Flag | Meaning |
|---|---|
| `--batch MANIFEST` | Run batch conversion from a YAML manifest (mutually exclusive with `FILE`). |
| `-o`, `--output PATH` | **Required.** A directory (per-file mode) or a file path (assemble mode). |
| `--fail-fast` | Stop at the first source that is not `converted` (default: partial completion with per-file honesty). |
| `--json` | Print the `BatchReport` as JSON (stdout stays pure JSON; status goes to stderr). |

**The manifest grammar.** A YAML mapping with an **ordered** `sources` list (one literal path *or*
glob per entry — resolved deterministically, and manifest order is processing/report order), **one**
`target`, and optional per-source `overrides`. It has *no* fields for selection, splitting, or
deduplication — those are rejected (the scope refusal), because curation is a scientific judgment
about data, not a translation of it.

```yaml
sources:
  - path: "./inputs/*.xyz"            # literal paths and globs mix
  - path: "./inputs/step.db"          # a multi-row .db fans out to N per-row conversions
    override:
      mode: strict                     # per-file override replaces the shared setting
  - "./inputs/single.xyz"             # a bare string is a source with no override
target: extxyz
output_mode: per-file                  # "per-file" (default) or "assemble"
mode: permissive
recovery_choices:                      # the same --recover grammar: SCENARIO=CHOICE[,param=value…]
  - "missing_lattice=bounding_box,padding_ang=5.0"
tolerance_profile: default
acknowledge_loss: false
acknowledge_parse_warnings: false
```

Per-file `override` fields (`mode`, `recovery_choices`, `tolerance_profile`, `acknowledge_loss`,
`acknowledge_parse_warnings`) replace the shared value for that one source; `recovery_choices`
*replaces* (never merges) the manifest's preset list.

**Output modes.** `per-file` (default) writes one converted file per source into `-o` as a directory
(a multi-row `.db` writes one file per row, named `<stem>.rowNNNN`); `assemble` combines the
converted sources into **one** artifact at `-o` through the target's declared assemble capability
(a multi-frame extXYZ / multi-row ASE `.db` dataset container). For a **directory-format target**
such as `deepmd_npy`, `assemble` writes a `system_NNN/` tree — grouping sources by composition into
one system per group — and the report's aggregate `note` and each converted entry's `system` field
record **which source landed in which `system_NNN`**. A multi-row `.db` in a batch is a fan-out: each
row becomes an independent per-row conversion (the rows are a dataset, never one merged structure).

**Exit code.** The batch exits with the **worst per-file outcome** under the 0–5 vocabulary below
(each entry folds through the same single-file logic with its effective mode): a failed file is `4`
(parse error), a refused file is `2`, validation failures are `3`, and so on. A malformed manifest or
a manifest-level refusal (unknown target, an `assemble` to a non-assemble-capable target) is a usage
error (`1`) — it never produces a partial run.

## validate

Re-parse a converted file and diff it against the source within tolerance, or re-threshold a
previously stored Validation Report against a different tolerance profile.

```
xtalate validate [--output FILE --source FILE --conversion-report PATH]
                 [--validation-report PATH]
                 [--tolerance-profile NAME|FILE] [--json]
```

| Flag | Meaning |
|---|---|
| `--output FILE` | The converted output file (full re-parse mode). |
| `--source FILE` | The original source file (full re-parse mode). |
| `--conversion-report PATH` | The `ConversionReport` JSON (full re-parse mode). |
| `--validation-report PATH` | Write the report (full re-parse), or — passed alone — read it to re-threshold. |
| `--tolerance-profile NAME\|FILE` | The tolerance profile to validate under. |
| `--json` | Print the `ValidationReport` JSON. |

## capabilities

Print the Capability Matrix — what each format can and cannot express — for all formats or one.

```
xtalate capabilities [FORMAT_ID] [--json]
```

| Flag | Meaning |
|---|---|
| `FORMAT_ID` | Limit output to a single format. |
| `--json` | Print the matrix as JSON. |

## scenarios

Print the recovery-scenario catalog: every scenario, its choices and what each choice supplies, so you
know what `--recover` accepts before a conversion refuses.

```
xtalate scenarios [SCENARIO] [--json]
```

| Flag | Meaning |
|---|---|
| `SCENARIO` | Limit output to one scenario (e.g. `ambiguous_stress_convention`). |
| `--json` | Print the catalog as JSON. |

## Shell completion

Optional: `pip install "xtalate[completion]"`, then add `eval "$(register-python-argcomplete xtalate)"`
to your shell profile.

## Exit codes

The CLI is CI-native: it signals the outcome through the process exit code, so a script never has to
parse stdout. These six codes are the frozen 1.x contract.

| Code | Meaning |
|---|---|
| `0` | OK. |
| `1` | Usage or internal error (a bad flag, an unreadable file, a broken installed plugin, an invalid `--recover` preset or tolerance profile). |
| `2` | Refused — a first-class outcome, not a crash: the conversion declined rather than guess at data the source lacks. |
| `3` | Validation failed. |
| `4` | Parse error. |
| `5` | Passed with warnings under `--mode strict`. |

In batch mode (`convert --batch`) the process exits with the **worst per-file outcome** under this
exact ladder — each entry folds through the same 0–5 mapping with its effective mode, and the maximum
wins — while `1` still names a *manifest* mistake (a malformed manifest, an unknown target, an
`assemble` to a non-assemble-capable target).
