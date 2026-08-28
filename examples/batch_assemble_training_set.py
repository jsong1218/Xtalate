"""Xtalate demo — the roadmap's stopping point, end to end: several real source files of
different DFT/MD ecosystems → **one extXYZ MLIP training set** with one aggregate record.

Run from the repo root::

    python examples/batch_assemble_training_set.py [OUTPUT.extxyz]

It drives a handful of **committed real fixtures** — a VASP ``vasprun.xml`` (relax), a VASP
``OUTCAR`` (relax), a Quantum ESPRESSO ``pw.out`` (scf), and a LAMMPS ``dump.lammpstrj``
(units declared) — through the library batch surface (:func:`run_batch`, v1.5 M54) in
``assemble`` mode: every file converts through the **ordinary single-file path** (the same
``parse_with_recovery`` + engine a lone ``xtalate convert`` takes; the batch re-implements
none of it), and the target's declared assemble capability (M55-S4/D208) concatenates the
per-source outputs into one file. The aggregate record — the ``BatchReport`` — embeds each
file's own ``ConversionReport``/``ValidationReport`` **verbatim** and tallies counts only
(MASTER_SPEC Part 6 preamble, D201): no merged assumptions, no "top losses" digest, no
selection/splitting/deduplication. **Aggregation, never curation** (roadmap §11): the batch
converts what it is given, completely and reported — it never decides which frames or files
"belong" in the training set.

The sources differ in composition (H₂O vs. Si), so the assembled artifact is a **valid MLIP
training set with variable N across frames** — a real property of the file, stated in the
report's dataset-level note (a single-object re-parse of the whole file would refuse
``EXTXYZ_VARIABLE_ATOM_COUNT``; per-file validations of each contribution stay green). The
example prints that note verbatim — **zero silently absorbed anomalies**: every per-file
outcome and every dataset-level statement is printed, never elided.

Nothing here is bespoke to these four files: the same :func:`run_batch` converts any
manifest — this script's ``SOURCES`` list is the whole "directory of files" the roadmap's
stopping point is about, at fixture scale.
"""

from __future__ import annotations

import sys
from pathlib import Path

from xtalate.capabilities import Registry
from xtalate.conversion.batch import BatchManifest, BatchReport, run_batch
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers

# The repo root, so the example runs from any working directory: the fixtures are committed
# real files under tests/golden/ (VASP vasprun.xml + OUTCAR, QE pw.out, LAMMPS dump).
ROOT = Path(__file__).resolve().parents[1]

SOURCES: list[str] = [
    "tests/golden/vasprun/relax-h2o/vasprun.xml",
    "tests/golden/qe_pw_out/scf/pw.out",
    "tests/golden/lammps_dump/si-ortho-declared/dump.lammpstrj",
    "tests/golden/outcar/relax-h2o/OUTCAR",
]


def build_registry() -> Registry:
    registry = Registry()
    for parser in builtin_parsers():
        registry.register_parser(parser)
    for exporter in builtin_exporters():
        registry.register_exporter(exporter)
    return registry


def print_batch_report(report: BatchReport) -> None:
    """A human view of the aggregate — computes nothing the model does not already hold."""
    print(
        f"Batch Report  [{report.tallies.converted} converted · {report.tallies.refused} "
        f"refused · {report.tallies.failed} failed]"
    )
    print(f"  target: {report.manifest.target}  ({report.manifest.output_mode})")
    for entry in report.entries:
        if entry.status == "converted":
            status = entry.validation.status if entry.validation is not None else "converted"
            print(f"  ✓ {entry.source}  converted [{status}]")
        elif entry.status == "refused":
            code = entry.conversion.refusal.get("code", "") if entry.conversion is not None else ""
            print(f"  ✗ {entry.source}  refused [{code}]")
        else:
            code = entry.error.code if entry.error is not None else ""
            message = entry.error.message if entry.error is not None else ""
            print(f"  ✗ {entry.source}  failed [{code}]: {message}")
    labels = report.tallies.label_presence
    print(f"  labels: {labels.energy} energy · {labels.forces} forces · {labels.stress} stress")
    if report.note:
        # The assembled-file variable-N statement (M54-S2): a property of the assembled
        # artifact, never a per-file loss — stated aloud, the way the record keeps it.
        print("  mixed-composition note:")
        print(f"    {report.note}")


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "training_set.extxyz"
    sources = [str(ROOT / source) for source in SOURCES]

    manifest = BatchManifest(
        sources=sources,
        target="extxyz",
        output_mode="assemble",
    )

    registry = build_registry()
    report = run_batch(manifest, registry, output=output)

    print_batch_report(report)
    print()
    if report.tallies.converted == report.tallies.total:
        print(f"Wrote the assembled training set to {output} ({output.stat().st_size} bytes).")
    else:
        print(
            f"Batch did not fully convert — {report.tallies.refused} refused, "
            f"{report.tallies.failed} failed (see the per-file lines above)."
        )


if __name__ == "__main__":
    main()
