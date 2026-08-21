"""Xtalate demo — the write-direction flagship: relaxed extXYZ → a LAMMPS *data* restart, in full.

Run from the repo root::

    python examples/convert_extxyz_to_lammps_data.py

It takes a relaxed structure in extended-XYZ (a labelled final geometry — the shape that falls out
of an MLIP relaxation) and writes the **restart** a production LAMMPS run reads back in: a
``lammps_data`` configuration file. This is the *deploy* arrow of the version, the mirror of
``convert_lammps_dump_to_extxyz.py`` (the read/relabel arrow): together they close the round the
whole v1.3 story is about — **train** (extXYZ) → **deploy** (a data restart) → **produce** (a
LAMMPS dump) → **relabel** (extXYZ again).

A data file is the first write target whose output *cannot self-describe* (M48, D181), and this demo
shows exactly what that costs and how each cost is paid explicitly, never silently (P1/P4):

* **No unit system.** A data file states no units, so *writing* one must declare the style its
  numbers are in — supplied here as ``ambiguous_units=metal`` and recorded as an Assumption. (An
  undeclared choice would refuse, never default — P4.)
* **No masses in the source.** extXYZ carries species and positions but no per-atom masses, and a
  data file *requires* a ``Masses`` table. The gap is filled by the explicit
  ``missing_masses=standard_masses`` recovery — IUPAC standard atomic weights — and reported as a
  ``supplied`` entry with its Assumption, the plain-language "filled masses …" the mission promises.
  It is fabricated by a recorded choice, never invented behind the user's back.
* **Atoms identified by number, not symbol.** A data file lists numeric atom *types*, so the
  exporter assigns them by first appearance (``type 1 → Si, type 2 → O``) and **reports the whole
  map** (``LAMMPSDATA_TYPES_ASSIGNED``) — the key a reader needs to turn the restart's numbers back
  into chemistry.

Everything the target cannot hold is predicted before the write (P5) and stated in the Conversion
Report, and the Validation Report Xtalate produces for every conversion re-parses the output —
through the exporter's recovery-aware ``reparse_recovery`` hook, because the bytes cannot
self-describe — and checks the report told the truth (Part 5). Finally it prints the ``lammps_data``
restart bytes.

This is the roadmap §4 stopping point made runnable, **write direction**. Nothing here is bespoke to
the extXYZ→data pair; the same engine converts any registered pair from the formats' own capability
declarations.
"""

from __future__ import annotations

import hashlib

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.validation import ValidationReport

# A relaxed final geometry in extended-XYZ: one frame, a periodic cubic cell, three atoms over two
# species (Si, O). Labelled and positioned — but, like any extXYZ, carrying no per-atom masses.
RELAXED_EXTXYZ = """\
3
Lattice="6.0 0.0 0.0 0.0 6.0 0.0 0.0 0.0 6.0" Properties=species:S:1:pos:R:3 pbc="T T T"
Si 0.00 0.00 0.00
O  1.60 1.60 1.60
O  3.20 3.20 0.00
"""

# The two recoveries the write to a data file needs, both explicit and both recorded as
# Assumptions: declare the unit style the values are written in, and fill the Masses table extXYZ
# never carried. Built as dicts rather than the CLI's `--recover ambiguous_units=metal --recover
# missing_masses=standard_masses` strings; the two are equivalent (Part 4 §3.3).
DATA_RECOVERY: dict[str, dict[str, object]] = {
    "ambiguous_units": {"choice": "metal", "parameters": {}},
    "missing_masses": {"choice": "standard_masses", "parameters": {}},
}


def build_registry() -> Registry:
    registry = Registry()
    for parser in builtin_parsers():
        registry.register_parser(parser)
    for exporter in builtin_exporters():
        registry.register_exporter(exporter)
    return registry


def print_report(report: ConversionReport) -> None:
    print(f"Conversion Report  [{report.stage} · {report.status} · {report.mode}]")
    print(f"  {report.source['format_id']} → {report.target['format_id']}")
    print(f"  preserved ({len(report.preserved)}):")
    for entry in report.preserved:
        suffix = f"  — {entry.detail}" if entry.detail else ""
        print(f"    ✓ {entry.path}{suffix}")
    print(f"  removed ({len(report.removed)}):")
    for removed in report.removed:
        print(f"    ✗ {removed.path}  — {removed.reason}")
    print(f"  supplied ({len(report.supplied)}):")
    for supplied in report.supplied:
        print(f"    + {supplied.path}  — {supplied.detail}")
    print(f"  warnings ({len(report.warnings)}):")
    for warning in report.warnings:
        print(f"    ⚠ [{warning.source}] {warning.message}")
    print(f"  assumptions ({len(report.assumptions)}):")
    for assumption in report.assumptions:
        print(f"    · {assumption.scenario} = {assumption.choice}: {assumption.description}")


def print_validation(report: ValidationReport) -> None:
    glyph = {"pass": "✓", "warn": "⚠", "fail": "✗", "skipped": "–"}
    print(f"Validation Report  [{report.status}]  (profile: {report.tolerance_profile['name']})")
    for check in report.checks:
        print(f"    {glyph.get(check.status, '?')} {check.check_id}: {check.message}")


def main() -> None:
    registry = build_registry()
    engine = ConversionEngine(registry)

    raw = RELAXED_EXTXYZ.encode()
    # Parse with the mass recovery applied up front (parse-time), exactly as the CLI does before
    # handing the recovered object to the engine. extXYZ is self-describing, so no format override
    # is needed; the unit-style choice is a *write*-side recovery, threaded to the engine below.
    parsed = parse_with_recovery(
        registry,
        raw,
        filename="relaxed.extxyz",
        recovery_choices=DATA_RECOVERY,
    )

    result = engine.convert(
        parsed.canonical,
        source_format_id="extxyz",
        target_format_id="lammps_data",
        source_filename="relaxed.extxyz",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        target_filename="restart.data",
        parse_recovery=parsed,
        recovery_choices=DATA_RECOVERY,
    )

    print_report(result.report)
    print()
    assert result.validation is not None
    print_validation(result.validation)
    print("\n----- lammps_data restart output -----")
    assert result.output is not None
    print(result.output.decode())


if __name__ == "__main__":
    main()
