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

Every command exits non-zero on failure and can emit machine-readable JSON with `--json`.

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
                [--report PATH] [--validation-report PATH] [--json]
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

A conversion that would need data the source lacks does not guess — it refuses unless you supply the
value with `--recover`. See the [Developer Guide](./developer-guide) for the recovery scenarios.

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
