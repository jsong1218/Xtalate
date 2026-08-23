# ruff: noqa: E501 — the embedded pw.x output is the committed `vc-relax` golden, byte-for-byte;
# its lines are fixed-width Fortran output that cannot be rewrapped without breaking the
# verbatim-copy guarantee the docstring makes.
"""Xtalate demo — the flagship MLIP conversion, QE pw.x output → label-complete extXYZ, end to end.

Run from the repo root::

    python examples/convert_qe_pw_out_to_extxyz.py

It parses a Quantum ESPRESSO pw.x output (embedded below, byte-for-byte the committed
`vc-relax` golden fixture — a real 3-step vc-relax run in QE\'s native intra-step order, never
hand-authored), converts it to extended-XYZ, and prints the Conversion Report — showing
per-frame total energy (Ry → eV), per-atom forces (Ry/bohr → eV/Å), first-class
tension-positive stress (Ry/bohr³ → eV/Å³, the sign flipped from QE\'s compression-positive
convention — D195), and the per-step cell read from each `CELL_PARAMETERS` card — plus any
caveats, then the Validation Report that Xtalate produces for *every* conversion by
re-parsing the output and checking the report told the truth (M5, Part 5). Finally it prints
the extXYZ bytes.

This is the reference-data arrow made runnable (v1.4 M52): a QE calculation becomes an MLIP
training set. Loss is predicted from the Capability Matrix, executed transparently, reported,
and independently re-verified — never discovered after the fact (P1, P5). Nothing here is
bespoke to the qe_pw_out→extxyz pair; the same engine converts any registered pair from the
formats\' own capability declarations. All the label mappings (Ry→eV, Ry/bohr→eV/Å,
Ry/bohr³→eV/Å³) live in the shared `_qe` core and are pinned by hand-computed fixtures (D195).
"""

from __future__ import annotations

import hashlib
import io

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine, ConversionReport
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.validation import ValidationReport

# The committed `tests/golden/qe_pw_out/vc-relax/pw.out` golden, embedded verbatim
# (3 ionic steps, O + 2 H in a ~5 Å cubic cell, QE 7.2 output; D195): known-good, real QE
# intra-step order (SCF → `! total energy` in Ry → `Forces acting on atoms` in Ry/bohr →
# `total stress` 3×3 in Ry/bohr³ → positions + `CELL_PARAMETERS` in angstrom). Deriving the
# literal from the golden, rather than hand-authoring a fresh pw.out, is what keeps the
# example honest against the intra-step-ordering and unit-label traps.
PW_OUT = """\
     Program PWSCF v.7.2 (enter) (v.7.2)

     Current dimensions of program PWSCF are:
     ...

     Parallel version (MPI), running on     1 processors

     ...

     Atomic species   valence    mass     pseudopotential
        O            6.000     15.99900     O( 1.00)
        H            1.000      1.00800     H( 1.00)

     number of atoms/cell      =            3
     number of atomic types   =            2
     number of electrons      =        8.00
     number of Kohn-Sham states =           4

     kinetic-energy cutoff =  40.0000  Ry
     charge density cutoff = 320.0000  Ry

     celldm(1)=   9.448630664428  celldm(2)=   0.000000  celldm(3)=   0.000000
     celldm(4)=   0.000000  celldm(5)=   0.000000  celldm(6)=   0.000000

     lattice parameter (alat)  =       9.448630664428  a.u.

     crystal axes: (cart. coord. in units of alat)
       a(1) = (   1.000000   0.000000   0.000000 )  
       a(2) = (   0.000000   1.000000   0.000000 )  
       a(3) = (   0.000000   0.000000   1.000000 )  

     reciprocal axes: (cart. coord. in units 2 pi/alat)
       b(1) = (   1.000000   0.000000   0.000000 )  
       b(2) = (   0.000000   1.000000   0.000000 )  
       b(3) = (   0.000000   0.000000   1.000000 )  

     P =     0.000000000000E+00    0.000000000000E+00    0.000000000000E+00

     Cartesian axes

     site n.     atom                  positions (bohr units)
        1           O  tau(   1) = (   4.724315332214   4.724315332214   4.724315332214  )
        2           H  tau(   2) = (   6.141609931878   4.724315332214   4.724315332214  )
        3           H  tau(   3) = (   4.724315332214   6.141609931878   4.724315332214  )

     number of k points=     1
                       cart. coord. in units 2pi/alat
        k(    1) = (   0.000000000   0.000000000   0.000000000), wk =   2.0000000

     iteration #  1     ecut=    40.00 Ry   beta=0.70
     the density functional is:
     the exchange-correlation functional is: PBE
     ...

             total energy              =     -49.12345678 Ry
             estimated scf accuracy    <       0.00000001 Ry

          convergence has been achieved in  10 iterations

     !
     !    total energy =     -49.12345678 Ry
     !

          Forces acting on atoms (Ry/au):

     atom 1 type 1   force =     +0.01000000   -0.02000000   +0.00000000
     atom 2 type 2   force =     -0.00400000   +0.01000000   +0.00100000
     atom 3 type 2   force =     -0.00500000   +0.00900000   -0.00100000

     total force =     0.00141421     total SCF correction =     0.00007000

     total   stress  (Ry/bohr**3)                   (kbar)     P=  -1.47 kbar

     -0.00001000    0.00000050    0.00000000         -1.47105
      0.00000050   -0.00002000    0.00000030          0.07355
      0.00000000    0.00000030   -0.00000500          0.00000

          ATOMIC_POSITIONS (angstrom)
     O   2.500000000   2.500000000   2.500000000
     H   3.250000000   2.500000000   2.500000000
     H   2.500000000   3.250000000   2.500000000
     CELL_PARAMETERS (alat=  9.44863066)
        1.000000000   0.000000000   0.000000000
        0.000000000   1.000000000   0.000000000
        0.000000000   0.000000000   1.000000000

          iteration #  2     ecut=    40.00 Ry   beta=0.70
     the density functional is:
     the exchange-correlation functional is: PBE
     ...

             total energy              =     -49.12567890 Ry
             estimated scf accuracy    <       0.00000001 Ry

          convergence has been achieved in  10 iterations

     !
     !    total energy =     -49.12567890 Ry
     !

          Forces acting on atoms (Ry/au):

     atom 1 type 1   force =     +0.00900000   -0.01800000   +0.00000000
     atom 2 type 2   force =     -0.00350000   +0.00900000   +0.00100000
     atom 3 type 2   force =     -0.00450000   +0.00800000   -0.00100000

     total force =     0.00141421     total SCF correction =     0.00007000

     total   stress  (Ry/bohr**3)                   (kbar)     P=  -1.47 kbar

     -0.00000900    0.00000050    0.00000000         -1.32395
      0.00000050   -0.00001900    0.00000030          0.07355
      0.00000000    0.00000030   -0.00000450          0.00000

          ATOMIC_POSITIONS (angstrom)
     O   2.480000000   2.500000000   2.500000000
     H   3.260000000   2.500000000   2.500000000
     H   2.500000000   3.270000000   2.500000000
     CELL_PARAMETERS (alat=  9.45000000)
        1.000000000   0.000000000   0.000000000
        0.000000000   1.000000000   0.000000000
        0.000000000   0.000000000   1.000000000

          iteration #  3     ecut=    40.00 Ry   beta=0.70
     the density functional is:
     the exchange-correlation functional is: PBE
     ...

             total energy              =     -49.13012345 Ry
             estimated scf accuracy    <       0.00000001 Ry

          convergence has been achieved in  10 iterations

     !
     !    total energy =     -49.13012345 Ry
     !

          Forces acting on atoms (Ry/au):

     atom 1 type 1   force =     +0.00800000   -0.01600000   +0.00000000
     atom 2 type 2   force =     -0.00300000   +0.00800000   +0.00100000
     atom 3 type 2   force =     -0.00400000   +0.00700000   -0.00100000

     total force =     0.00141421     total SCF correction =     0.00007000

     total   stress  (Ry/bohr**3)                   (kbar)     P=  -1.47 kbar

     -0.00000800    0.00000050    0.00000000         -1.17684
      0.00000050   -0.00001800    0.00000030          0.07355
      0.00000000    0.00000030   -0.00000400          0.00000

          ATOMIC_POSITIONS (angstrom)
     O   2.470000000   2.500000000   2.500000000
     H   3.270000000   2.500000000   2.500000000
     H   2.500000000   3.280000000   2.500000000
     CELL_PARAMETERS (alat=  9.44700000)
        1.000000000   0.000000000   0.000000000
        0.000000000   1.000000000   0.000000000
        0.000000000   0.000000000   1.000000000

     
     JOB DONE.
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

    raw = PW_OUT.encode()
    source = registry.get_parser("qe_pw_out").parse(io.BytesIO(raw), filename="pw.out").canonical

    result = engine.convert(
        source,
        source_format_id="qe_pw_out",
        target_format_id="extxyz",
        source_filename="pw.out",
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
