"""Xtalate demo — the relabeling flagship: a relaxed extXYZ structure → a QE pw.x *input* setup.

Run from the repo root::

    python examples/convert_extxyz_to_qe_pw_in.py

It takes a relaxed structure in extended-XYZ (a labelled final geometry — the shape that falls out
of an MLIP relaxation) and writes the **relabeling setup** a DFT run reads in: a ``qe_pw_in``
pw.x input. This is the *relabel* arrow of the roadmap's train→deploy→produce→relabel loop —
production frames get re-labelled with DFT — and it carries the version's central honesty
decision (M51, D193):

> **Xtalate writes calculation *structures*, not calculation *science*.**

A *runnable* pw.x input needs physics the Canonical Object legitimately lacks: a plane-wave
cutoff (``ecutwfc``), a k-point mesh, and pseudopotential files. This demo shows what that costs,
and how each cost is paid explicitly, never silently (P1/P4):

* **No masses in the source.** extXYZ carries species and positions but no per-atom masses, and a
  pw.x input *requires* an ``ATOMIC_SPECIES`` mass column. The gap is filled by the explicit
  ``missing_masses=standard_masses`` recovery — IUPAC standard atomic weights — and reported as a
  ``supplied`` entry with its Assumption. (Masses have a legitimate generic fill; the *physics*
  below does not.)
* **The physics is named, not invented.** The source carries no ``ecutwfc``, no k-points, and no
  pseudopotential files — and the exporter writes **none** of them. No defaulted cutoff, no
  defaulted mesh: the written file carries a placeholder pseudopotential token that cannot be
  mistaken for a real file (``__PSEUDOPOTENTIAL_NOT_PROVIDED__.UPF`` — pw.x fails loudly on it),
  and the Conversion Report's **``QEIN_INCOMPLETE_INPUT`` warning names every entry the user must
  supply before pw.x will run**. The demo prints that warning line, so the
  "structurally complete, not yet runnable" story is visible in the output.
* **``ibrav = 0`` always.** The cell is written as explicit ``CELL_PARAMETERS {angstrom}`` — never
  reverse-derived into an ``ibrav`` code (D43).

Everything the target cannot hold is predicted before the write (P5) and stated in the Conversion
Report, and the Validation Report Xtalate produces for every conversion re-parses the output and
checks the report told the truth (Part 5). Finally it prints the pw.x input bytes.

This is the roadmap §4 stopping point made runnable, **write direction**. Nothing here is bespoke
to the extXYZ→qe_pw_in pair; the same engine converts any registered pair from the formats' own
capability declarations.
"""

from __future__ import annotations

import hashlib

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.validation import ValidationReport

# A relaxed final geometry in extended-XYZ: one frame, a periodic cubic cell, two atoms over one
# species (Fe). Labelled and positioned — but, like any extXYZ, carrying no per-atom masses and no
# calculation physics.
RELAXED_EXTXYZ = """\
1
Lattice="3.5 0.0 0.0 0.0 3.5 0.0 0.0 0.0 3.5" Properties=species:S:1:pos:R:3 pbc="T T T"
Fe 0.00 0.00 0.00
"""

# The one recovery the write to a pw.x input needs, explicit and recorded as an Assumption: fill
# the ATOMIC_SPECIES mass column extXYZ never carried (IUPAC standard atomic weights). The physics
# gaps are *not* presets — they are reported as the QEIN_INCOMPLETE_INPUT warning, never invented.
QE_RECOVERY: dict[str, dict[str, object]] = {
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
    parsed = parse_with_recovery(
        registry,
        raw,
        filename="relaxed.extxyz",
        recovery_choices=QE_RECOVERY,
    )

    result = engine.convert(
        parsed.canonical,
        source_format_id="extxyz",
        target_format_id="qe_pw_in",
        source_filename="relaxed.extxyz",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        target_filename="relaxed.in",
        parse_recovery=parsed,
        recovery_choices=QE_RECOVERY,
    )

    print_report(result.report)
    print()
    assert result.validation is not None
    print_validation(result.validation)
    print("\n----- qe_pw_in input output -----")
    assert result.output is not None
    print(result.output.decode())


if __name__ == "__main__":
    main()
