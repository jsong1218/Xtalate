"""Xtalate demo — a cross-format conversion with its Conversion Report *and* Validation Report.

Run from the repo root::

    python examples/convert_extxyz_to_poscar.py

It parses an extended-XYZ structure, converts it to POSCAR, and prints the Conversion
Report — showing exactly what was preserved, what was removed and *why*, and any caveats —
then the Validation Report that Xtalate produces for *every* conversion by re-parsing the
output and checking the report told the truth (M5, Part 5). Finally it prints the POSCAR bytes.
This is the payoff of the whole pipeline: loss is predicted from the Capability Matrix, executed
transparently, reported, and independently re-verified — never discovered after the fact (P1, P5).
Nothing here is bespoke to the extXYZ→POSCAR pair — the same engine converts any registered pair
from the formats' own capability declarations.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.validation import ValidationReport

SOURCE = (
    Path(__file__).parent.parent / "tests" / "golden" / "extxyz" / "co-in-cell" / "sample.extxyz"
)


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


def print_validation(report: ValidationReport) -> None:
    glyph = {"pass": "✓", "warn": "⚠", "fail": "✗", "skipped": "–"}
    print(f"Validation Report  [{report.status}]  (profile: {report.tolerance_profile['name']})")
    for check in report.checks:
        print(f"    {glyph.get(check.status, '?')} {check.check_id}: {check.message}")


def main() -> None:
    registry = build_registry()
    engine = ConversionEngine(registry)

    raw = SOURCE.read_bytes()
    source = registry.get_parser("extxyz").parse(io.BytesIO(raw), filename=SOURCE.name).canonical

    result = engine.convert(
        source,
        source_format_id="extxyz",
        target_format_id="poscar",
        source_filename=SOURCE.name,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        target_filename="POSCAR",
    )

    print_report(result.report)
    print()
    assert result.validation is not None
    print_validation(result.validation)
    print("\n----- POSCAR output -----")
    assert result.output is not None
    print(result.output.decode())


if __name__ == "__main__":
    main()
