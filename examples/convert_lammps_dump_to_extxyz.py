"""Xtalate demo — the read-direction flagship, LAMMPS dump → relabeling-ready extXYZ, end to end.

Run from the repo root::

    python examples/convert_lammps_dump_to_extxyz.py

It parses an MLIP-production LAMMPS text dump (embedded below) and converts it to extended-XYZ —
the shape an MLIP training pipeline wants: one species-labelled frame per snapshot. A production
dump is *typed*: it lists numeric atom types (``1``, ``2``), never element symbols, because LAMMPS
does not know the chemistry. Element symbols are required to write a relabeling-ready extXYZ and
**did not exist in the file**, so they are supplied through the explicit ``missing_species``
recovery (``species_map:1=Si,2=O``) and recorded as an Assumption — fabricated by a recorded
choice, never guessed (P4). The dump *declares* its unit style with an ``ITEM: UNITS`` preamble
(``metal``), so units are already explicit and no ``ambiguous_units`` recovery is needed; an
undeclared dump would refuse until a style is chosen (M46).

The dump also carries two per-atom columns with no canonical home — a compute (``c_pe``) and a fix
(``f_ave``). Neither is dropped silently: each is carried verbatim under a ``lammps_dump:`` key and
its fate is reported (a per-frame-varying column cannot ride a single extXYZ ``Properties=`` slot,
so its removal is stated, not hidden — P1). After the Conversion Report, the Validation Report that
Xtalate produces for *every* conversion re-parses the output and checks the report told the truth
(M5, Part 5). Finally it prints the extXYZ bytes.

This is the roadmap §4 stopping point made runnable, **read direction**: the single highest-demand
LAMMPS-output conversion — a typed production dump turned into a label-complete training file —
driven through the ordinary pipeline. The **write** direction (extXYZ → a ``lammps_data`` restart)
is the M48 flagship, not this one. Nothing here is bespoke to the dump→extXYZ pair; the same engine
converts any registered pair from the formats' own capability declarations.

Note on ``format_override``: LAMMPS writes the ``ITEM: UNITS`` preamble *before* ``ITEM: TIMESTEP``,
and the sniffer keys on a leading ``ITEM: TIMESTEP`` (M46), so a units-declaring dump is named
explicitly here — the same as passing ``--format lammps_dump`` to the CLI.
"""

from __future__ import annotations

import hashlib

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.validation import ValidationReport

# A minimal MLIP-production dump: two snapshots, four atoms, numeric types 1/2, a declared `metal`
# unit style, and two unmapped per-atom columns — `c_pe` (a per-atom compute, varies across frames)
# and `f_ave` (a per-atom fix, constant here). Real production order: the `UNITS` preamble first,
# then per-snapshot `TIMESTEP` / `NUMBER OF ATOMS` / `BOX BOUNDS` / `ATOMS` items.
PROD_DUMP = """\
ITEM: UNITS
metal
ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
4
ITEM: BOX BOUNDS pp pp pp
0.0 10.0
0.0 10.0
0.0 10.0
ITEM: ATOMS id type x y z c_pe f_ave
1 1 1.0 1.0 1.0 -3.50 0.10
2 2 2.0 2.0 2.0 -4.50 0.20
3 1 3.0 3.0 3.0 -3.40 0.11
4 2 4.0 4.0 4.0 -4.40 0.21
ITEM: TIMESTEP
100
ITEM: NUMBER OF ATOMS
4
ITEM: BOX BOUNDS pp pp pp
0.0 10.0
0.0 10.0
0.0 10.0
ITEM: ATOMS id type x y z c_pe f_ave
1 1 1.1 1.0 1.0 -3.51 0.10
2 2 2.1 2.0 2.0 -4.52 0.20
3 1 3.1 3.0 3.0 -3.41 0.11
4 2 4.1 4.0 4.0 -4.41 0.21
"""

# The one recovery a typed dump needs on the way to extXYZ: map each numeric atom type to its
# element symbol. Built as a dict rather than the CLI's
# `--recover missing_species=species_map:1=Si,2=O` string so the map is unambiguous in code; the
# two are equivalent (Part 4 §3.3).
SPECIES_RECOVERY: dict[str, dict[str, object]] = {
    "missing_species": {"choice": "species_map", "parameters": {"species": {1: "Si", 2: "O"}}},
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
    print(f"  warnings ({len(report.warnings)}):")
    for warning in report.warnings:
        print(f"    ⚠ [{warning.source}] {warning.message}")
    print(f"  supplied: {len(report.supplied)}   assumptions: {len(report.assumptions)}")
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

    raw = PROD_DUMP.encode()
    # Parse with the species recovery applied up front (parse-time), exactly as the CLI does before
    # handing the recovered object to the engine. The dump declares `metal`, so units need no
    # recovery; `format_override` names the format because the `ITEM: UNITS` preamble defeats the
    # leading-`ITEM: TIMESTEP` sniff (see the module docstring).
    parsed = parse_with_recovery(
        registry,
        raw,
        filename="prod.dump",
        format_override="lammps_dump",
        recovery_choices=SPECIES_RECOVERY,
    )

    result = engine.convert(
        parsed.canonical,
        source_format_id="lammps_dump",
        target_format_id="extxyz",
        source_filename="prod.dump",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        target_filename="train.extxyz",
        parse_recovery=parsed,
        recovery_choices=SPECIES_RECOVERY,
    )

    print_report(result.report)
    print()
    assert result.validation is not None
    print_validation(result.validation)
    print("\n----- extXYZ output -----")
    assert result.output is not None
    print(result.output.decode())


if __name__ == "__main__":
    main()
