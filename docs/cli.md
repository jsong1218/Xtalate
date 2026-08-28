# CLI reference

The `xtalate` command is a thin presenter over the library — the same engine the HTTP service uses.
It has four subcommands:

```
xtalate inspect       Run the Information Discovery Engine (✓/✗ inventory).
xtalate convert       Full pipeline: parse → pre-flight → recovery → export → validate.
xtalate validate      Offline re-parse re-validation, or re-threshold a stored report.
xtalate capabilities  Print the Capability Matrix.
```

Global:

```
xtalate --version     Print the version and exit.
```

Every command signals its outcome through the exit code (see [Exit codes](#exit-codes)) and can emit
machine-readable JSON with `--json`.

As of the v1.0 contract freeze, the CLI surface documented here — the four subcommands, their flags,
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
xtalate convert FILE --to FORMAT_ID [-o PATH] [--format FORMAT_ID]
                [--mode permissive|strict]
                [--recover "SCENARIO=CHOICE[,param=value…]"]…
                [--acknowledge-loss] [--acknowledge-parse-warnings]
                [--tolerance-profile NAME|FILE]
                [--report PATH] [--validation-report PATH] [--json] [--no-bell]
```

| Flag | Meaning |
|---|---|
| `FILE` | The source file. |
| `--to FORMAT_ID` | **Required.** Target format. |
| `-o`, `--output PATH` | Write the converted file to `PATH`. |
| `--format FORMAT_ID` | Override source-format sniffing. |
| `--mode permissive\|strict` | `strict` refuses on any predicted loss; `permissive` (default) reports it. |
| `--recover "SCENARIO=CHOICE[,param=value…]"` | Preset a recovery choice for a required-but-missing field. Repeatable. Every choice is recorded as an Assumption. |
| `--acknowledge-loss` | Proceed past reported loss non-interactively. |
| `--acknowledge-parse-warnings` | Proceed past parse warnings non-interactively. |
| `--tolerance-profile NAME\|FILE` | `default`, `strict`, `loose`, or a custom tolerance table (YAML/JSON) for validation. |
| `--report PATH` | Write the `ConversionReport` JSON. |
| `--validation-report PATH` | Write the `ValidationReport` JSON. |
| `--json` | Print both reports as one JSON object. |
| `--no-bell` | Do not ring the terminal bell when the conversion finishes. |

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
