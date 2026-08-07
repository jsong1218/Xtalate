# xtalate-example-format

The **reference third-party plugin** for [Xtalate](../../README.md). Copy it to add your own
format. It implements one deliberately small format — `exfmt` — using **only** the frozen public
Plugin SDK (`xtalate.sdk` + `xtalate.schema`), and it declares its own information loss honestly,
which is the point.

## The `exfmt` format

A single-frame text format: a magic header, an **optional** free-text label line, then one
`<symbol> <x> <y> <z>` row per atom, Cartesian ångström.

```
EXFMT 1
# water monomer, optimized geometry
O  0.0     0.0     0.0
H  0.9584  0.0     0.0
H -0.2396  0.9273  0.0
```

The label line (`# …`) is optional. Everything the format cannot express — cell, velocities,
energies, forces — is simply **absent** from the file, and the parser records it as `None`, never
a fabricated default (the absence convention, **P3**).

## Why it declares a loss on purpose

The parser reads the label into `user_metadata.custom_per_frame['exfmt:label']`. The **exporter
cannot write it back** — so its capability declaration marks that container `NONE` on the write
side. When you convert an `exfmt` file that has a label, the Conversion Report lists it as
`removed`, with a plain-language reason — it is never dropped silently (**P1**).

That is the lesson this plugin exists to teach: **declare capabilities honestly — a `PARTIAL` or
`NONE` field with a note beats an optimistic `FULL` that silently loses data.** (Contrast plain
XYZ, which declares the same container `PARTIAL` because it *can* write exactly one key, its
comment line: `NONE` and `PARTIAL` are the two honest shapes of "less than `FULL`".)

## Install and run

```bash
pip install ./plugins/example-format          # or `pip install --no-deps .` from this directory
xtalate capabilities --json                    # `exfmt` now appears, read + write
xtalate convert structure.exfmt --to xyz -o structure.xyz
```

Because the plugin registers through Xtalate's entry points, no change to Xtalate's core is
needed — installing the wheel is enough for `exfmt` to appear in the CLI, the format explorer,
and the round-trip matrix.

## Layout

```
plugins/example-format/
  pyproject.toml                     # entry points advertise exfmt under xtalate.parsers/.exporters
  src/xtalate_examplefmt/
    parser.py                        # ExampleFormatParser — reads exfmt (incl. the label)
    exporter.py                      # ExampleFormatExporter — writes exfmt (drops the label, honestly)
    py.typed
  tests/
    test_example_format.py           # the plugin's contract: discovery, goldens, round-trip, the removed label
    golden/exfmt/<case>/             # self-contained golden cases with licensed manifests
```

Licensed Apache-2.0, matching the parent repository.
