# ruff: noqa: E501 — the embedded OUTCAR is the committed `relax-h2o` golden, byte-for-byte;
# its three `in kB` stress lines exceed the line-length limit and cannot be wrapped without
# breaking the verbatim-copy guarantee the docstring makes.
"""Xtalate demo — the flagship MLIP conversion, VASP output → label-complete extXYZ, end to end.

Run from the repo root::

    python examples/convert_outcar_to_extxyz.py

It parses a VASP OUTCAR (embedded below, byte-for-byte the committed `relax-h2o` golden
fixture — real VASP intra-step order, never hand-authored), converts it to extended-XYZ, and
prints the Conversion Report — showing per-frame energy, per-atom forces, and first-class
tension-positive stress all preserved, plus any caveats — then the Validation Report that
Xtalate produces for *every* conversion by re-parsing the output and checking the report told
the truth (M5, Part 5). Finally it prints the extXYZ bytes.

This is the roadmap §3 stopping point made runnable: the single highest-demand MLIP conversion —
a VASP log into a label-complete training file — driven through the ordinary pipeline. Loss is
predicted from the Capability Matrix, executed transparently, reported, and independently
re-verified — never discovered after the fact (P1, P5). Nothing here is bespoke to the
OUTCAR→extXYZ pair; the same engine converts any registered pair from the formats' own
capability declarations.

`vasprun.xml --to extxyz` is identical in shape: VASP's XML output feeds the same shared `_vasp`
label core and the same engine, so this example deliberately covers one VASP-output format and
the other needs no duplicate.
"""

from __future__ import annotations

import hashlib
import io

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.validation import ValidationReport

# The committed `tests/golden/outcar/relax-h2o/OUTCAR` golden, embedded verbatim (3 ionic steps):
# known-good, real VASP intra-step order (stress before the force table, `energy(sigma->0)`
# after it — D167). Deriving the literal from the golden, rather than hand-authoring a fresh
# OUTCAR, is what keeps the example honest against the intra-step-ordering trap.
OUTCAR = """\
 vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex

  running on    1 total cores
  distrk:  each k-point on    1 cores,    1 groups
  distr:  one band on NCORES_PER_BAND=   1 cores,    1 groups

  POTCAR:    PAW_PBE H 15Jun2001
    VRHFIN =H: 1s1
    TITEL  = PAW_PBE H 15Jun2001
  POTCAR:    PAW_PBE O 15Jun2001
    VRHFIN =O: 2s2p4
    TITEL  = PAW_PBE O 15Jun2001

  ions per type =               2   1

  NIONS =       3

  direct lattice vectors                 reciprocal lattice vectors
     10.000000000  0.000000000  0.000000000     0.100000000  0.000000000  0.000000000
      0.000000000 10.000000000  0.000000000     0.000000000  0.100000000  0.000000000
      0.000000000  0.000000000 10.000000000     0.000000000  0.000000000  0.100000000

 ----------------------------------- Iteration   1(   1)  ---------------------------------------

    DAV:   1    -0.12E+02    0.5E+00    0.5E+00    0.5E+00

  FORCE on cell =-STRESS in cart. coord.  units (eV):
  Direction     XX          YY          ZZ          XY          YZ          ZX
  ---------------------------------------------------------------------------
    Alpha Z       0.00        0.00        0.00
    Ewald        -500.00     -500.00     -500.00      0.00        0.00        0.00
  ---------------------------------------------------------------------------
    Total         500.00      500.00      500.00      0.00        0.00        0.00
    in kB         1602.1766208000 3204.3532416000 801.0883104000 400.5441552000 200.2720776000 100.1360388000
    external pressure =      500.00 kB  Pullay stress =        0.00 kB

  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.50000000   5.00000000   0.20000000  -0.10000000  0.00000000
      7.50000000   5.00000000   5.00000000   -0.10000000  0.05000000  0.00000000
      5.00000000   5.00000000   5.00000000   -0.10000000  0.00000000  0.05000000
  -----------------------------------------------------------------------------
     total drift:                                0.00000000   0.00000000   0.00000000

  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
  -------------------------------------------------------------------
    free  energy   TOTEN  =       -76.40100000 eV

    energy  without entropy=       -76.40000000  energy(sigma->0) =       -76.40000000

 ----------------------------------- Iteration   2(   2)  ---------------------------------------

    DAV:   1    -0.12E+02    0.5E+00    0.5E+00    0.5E+00

  FORCE on cell =-STRESS in cart. coord.  units (eV):
  Direction     XX          YY          ZZ          XY          YZ          ZX
  ---------------------------------------------------------------------------
    Alpha Z       0.00        0.00        0.00
    Ewald        -500.00     -500.00     -500.00      0.00        0.00        0.00
  ---------------------------------------------------------------------------
    Total         500.00      500.00      500.00      0.00        0.00        0.00
    in kB         1602.1766208000 3204.3532416000 801.0883104000 400.5441552000 200.2720776000 100.1360388000
    external pressure =      500.00 kB  Pullay stress =        0.00 kB

  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.30000000   5.00000000   0.10000000  -0.05000000  0.00000000
      7.30000000   5.00000000   5.00000000   -0.05000000  0.02000000  0.00000000
      5.00000000   5.00000000   5.00000000   -0.05000000  0.00000000  0.02000000
  -----------------------------------------------------------------------------
     total drift:                                0.00000000   0.00000000   0.00000000

  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
  -------------------------------------------------------------------
    free  energy   TOTEN  =       -76.41100000 eV

    energy  without entropy=       -76.41000000  energy(sigma->0) =       -76.41000000

 ----------------------------------- Iteration   3(   3)  ---------------------------------------

    DAV:   1    -0.12E+02    0.5E+00    0.5E+00    0.5E+00

  FORCE on cell =-STRESS in cart. coord.  units (eV):
  Direction     XX          YY          ZZ          XY          YZ          ZX
  ---------------------------------------------------------------------------
    Alpha Z       0.00        0.00        0.00
    Ewald        -500.00     -500.00     -500.00      0.00        0.00        0.00
  ---------------------------------------------------------------------------
    Total         500.00      500.00      500.00      0.00        0.00        0.00
    in kB         1602.1766208000 3204.3532416000 801.0883104000 400.5441552000 200.2720776000 100.1360388000
    external pressure =      500.00 kB  Pullay stress =        0.00 kB

  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.40000000   5.00000000   0.01000000  -0.01000000  0.00000000
      7.40000000   5.00000000   5.00000000   -0.01000000  0.00500000  0.00000000
      5.00000000   5.00000000   5.00000000   -0.01000000  0.00000000  0.00500000
  -----------------------------------------------------------------------------
     total drift:                                0.00000000   0.00000000   0.00000000

  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
  -------------------------------------------------------------------
    free  energy   TOTEN  =       -76.42100000 eV

    energy  without entropy=       -76.42000000  energy(sigma->0) =       -76.42000000
"""


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

    raw = OUTCAR.encode()
    source = registry.get_parser("outcar").parse(io.BytesIO(raw), filename="OUTCAR").canonical

    result = engine.convert(
        source,
        source_format_id="outcar",
        target_format_id="extxyz",
        source_filename="OUTCAR",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        target_filename="traj.extxyz",
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
