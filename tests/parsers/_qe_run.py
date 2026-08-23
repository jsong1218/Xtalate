# ruff: noqa: E501 — the STEPS data rows and the embedded fixture line literals are the
# committed golden's byte-for-byte content and cannot be wrapped without breaking the
# verbatim-copy guarantee the module docstring makes.
"""Shared synthetic QE run for the M52 input-echo cross-check (not a test module).

One synthetic H2O calculation — 3 atoms (1 O + 2 H) in a 5 Å cubic cell — authored as **both**
its pw.x input and its pw.x output, from a single source of truth, so the M50 input parser and
the M52 output parser can be asserted to agree on the shared initial structure (cell / species /
positions): standing rule 4's guard that a silent unit or sign disagreement between the two QE
readers of one calculation cannot slip through (v1.4 M52-S1; D195).

The 7.x output rendering is byte-for-byte the committed ``tests/golden/qe_pw_out/relax/pw.out``
golden — the cross-check and the golden cannot drift apart. ``render_pw_out(\"6x\")`` (the QE 6.x
spelling of the same run) is M52-S2's addition.
"""

from __future__ import annotations

#: The declared lattice scale, bohr — × 0.52917720859 = 5.0000000000000 Å.
ALAT_BOHR = "9.448630664428"
#: 2.5 Å in bohr — the O atom's (x, y, z) and the H atoms' non-drifting axes.
X_BOHR = "4.724315332214"
#: 3.25 Å in bohr — the H atoms' off-center axis (3.25 × 1.8897261328856432, the Å→bohr
#: inverse of QE's bohr_radius_angs).
H_BOHR = "6.141609931878"

_SPECIES = [("O", 6.0, 15.999, "O( 1.00)"), ("H", 1.0, 1.008, "H( 1.00)")]
_SITE_LABELS = ["O", "H", "H"]

_HEADER = f"""\
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

     celldm(1)=   {ALAT_BOHR}  celldm(2)=   0.000000  celldm(3)=   0.000000
     celldm(4)=   0.000000  celldm(5)=   0.000000  celldm(6)=   0.000000

     lattice parameter (alat)  =       {ALAT_BOHR}  a.u.

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
        1           O  tau(   1) = (   {X_BOHR}   {X_BOHR}   {X_BOHR}  )
        2           H  tau(   2) = (   {H_BOHR}   {X_BOHR}   {X_BOHR}  )
        3           H  tau(   3) = (   {X_BOHR}   {H_BOHR}   {X_BOHR}  )

     number of k points=     1
                       cart. coord. in units 2pi/alat
        k(    1) = (   0.000000000   0.000000000   0.000000000), wk =   2.0000000

"""

#: The same run's QE **6.x** spelling (M52-S2) — the documented 6.x↔7.x drift the reader
#: must tolerate, in one header: a 6.x banner (``v.6.8``, no ``(v.6.8)`` suffix), the
#: lowercase ``atomic species`` table header, looser column widths in the species and site
#: tables, and an extra 6.x diagnostic block between the reciprocal axes and the site table.
#: Every number is identical to the 7.x header — only the *layout* drifts.
_HEADER_6X = f"""\
     Program PWSCF v.6.8 (enter)

     Current dimensions of program PWSCF are:
     ...

     Parallel version (MPI), running on     1 processors

     ...

     atomic species   valence    mass     pseudopotential
        O           6.000      15.99900     O( 1.00)
        H           1.000       1.00800     H( 1.00)

     number of atoms/cell      =            3
     number of atomic types   =            2
     number of electrons      =        8.00
     number of Kohn-Sham states =           4

     kinetic-energy cutoff =  40.0000  Ry
     charge density cutoff = 320.0000  Ry

     celldm(1)=   {ALAT_BOHR}  celldm(2)=   0.000000  celldm(3)=   0.000000
     celldm(4)=   0.000000  celldm(5)=   0.000000  celldm(6)=   0.000000

     lattice parameter (alat)  =       {ALAT_BOHR}  a.u.

     crystal axes: (cart. coord. in units of alat)
       a(1) = (   1.000000   0.000000   0.000000 )  
       a(2) = (   0.000000   1.000000   0.000000 )  
       a(3) = (   0.000000   0.000000   1.000000 )  

     reciprocal axes: (cart. coord. in units 2 pi/alat)
       b(1) = (   1.000000   0.000000   0.000000 )  
       b(2) = (   0.000000   1.000000   0.000000 )  
       b(3) = (   0.000000   0.000000   1.000000 )  

     G-vectors are generated in parallel using a custom distribution

     P =     0.000000000000E+00    0.000000000000E+00    0.000000000000E+00

     Cartesian axes

     site n.     atom                  positions (bohr units)
        1           O  tau(   1) = (  {X_BOHR}  {X_BOHR}  {X_BOHR} )
        2           H  tau(   2) = (  {H_BOHR}  {X_BOHR}  {X_BOHR} )
        3           H  tau(   3) = (  {X_BOHR}  {H_BOHR}  {X_BOHR} )

     number of k points=     1
                       cart. coord. in units 2pi/alat
        k(    1) = (   0.000000000   0.000000000   0.000000000), wk =   2.0000000

"""

#: The three ionic steps of the run: (energy Ry, forces Ry/bohr, stress diag Ry/bohr³, Å
#: positions) — the same numbers the committed relax golden carries.
STEPS: list[
    tuple[
        float,
        list[tuple[float, float, float]],
        tuple[float, float, float],
        list[tuple[float, float, float]],
    ]
] = [
    (
        -49.12345678,
        [
            (0.01000000, -0.02000000, 0.00000000),
            (-0.00400000, 0.01000000, 0.00100000),
            (-0.00500000, 0.00900000, -0.00100000),
        ],
        (-0.00001000, -0.00002000, -0.00000500),
        [(2.50, 2.50, 2.50), (3.25, 2.50, 2.50), (2.50, 3.25, 2.50)],
    ),
    (
        -49.12567890,
        [
            (0.00900000, -0.01800000, 0.00000000),
            (-0.00350000, 0.00900000, 0.00100000),
            (-0.00450000, 0.00800000, -0.00100000),
        ],
        (-0.00000900, -0.00001900, -0.00000450),
        [(2.48, 2.50, 2.50), (3.26, 2.50, 2.50), (2.50, 3.27, 2.50)],
    ),
    (
        -49.13012345,
        [
            (0.00800000, -0.01600000, 0.00000000),
            (-0.00300000, 0.00800000, 0.00100000),
            (-0.00400000, 0.00700000, -0.00100000),
        ],
        (-0.00000800, -0.00001800, -0.00000400),
        [(2.47, 2.50, 2.50), (3.27, 2.50, 2.50), (2.50, 3.28, 2.50)],
    ),
]


def _scf_iteration(iteration: int, total_energy: float) -> str:
    return f"""\
     iteration #  {iteration}     ecut=    40.00 Ry   beta=0.70
     the density functional is:
     the exchange-correlation functional is: PBE
     ...

             total energy              =     {total_energy:.8f} Ry
             estimated scf accuracy    <       0.00000001 Ry

     """


def _energy_line(total_energy: float) -> str:
    return f"""\
     !
     !    total energy =     {total_energy:.8f} Ry
     !

     """


def _forces_block(forces: list[tuple[float, float, float]], total_force: float) -> str:
    lines = ["     Forces acting on atoms (Ry/au):", ""]
    for atom, (fx, fy, fz) in enumerate(forces, start=1):
        t = 1 if atom == 1 else 2
        lines.append(f"     atom {atom} type {t}   force =     {fx:+.8f}   {fy:+.8f}   {fz:+.8f}")
    lines.append("")
    lines.append(
        f"     total force =     {total_force:.8f}     total SCF correction =     0.00007000"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _stress_block(diag: tuple[float, float, float]) -> str:
    tensor = [
        [diag[0], 0.00000050, 0.00000000],
        [0.00000050, diag[1], 0.00000030],
        [0.00000000, 0.00000030, diag[2]],
    ]
    kbar = [row[0] * 147105.07919960306 for row in tensor]
    rows = "\n".join(
        f"     {row[0]: .8f}   {row[1]: .8f}   {row[2]: .8f}         {k: .5f}"
        for row, k in zip(tensor, kbar, strict=True)
    )
    return f"""\
     total   stress  (Ry/bohr**3)                   (kbar)     P=  -1.47 kbar

{rows}

     """


def _positions_card(positions: list[tuple[float, float, float]]) -> str:
    lines = ["     ATOMIC_POSITIONS (angstrom)"]
    for label, (x, y, z) in zip(_SITE_LABELS, positions, strict=True):
        lines.append(f"     {label}   {x:.9f}   {y:.9f}   {z:.9f}")
    return "\n".join(lines) + "\n"


def render_pw_out(layout: str = "7x") -> str:
    """The run's pw.x output — the 7.x spelling (byte-for-byte the committed relax golden) or
    the 6.x spelling (M52-S2, byte-for-byte the committed ``relax-6x`` golden) — the same
    numbers, only the layout drifting (banner, capitalization, column widths, extra noise)."""
    header = _HEADER if layout == "7x" else _HEADER_6X
    for i, (energy, forces, diag, positions) in enumerate(STEPS):
        header += _scf_iteration(i + 1, energy)
        header += "     convergence has been achieved in  10 iterations\n\n"
        header += _energy_line(energy)
        header += _forces_block(forces, 0.00141421)
        header += _stress_block(diag)
        header += _positions_card(positions)
    return header + "\n     JOB DONE.\n"


def render_pw_in() -> str:
    """The run's pw.x input — the same cell / species / positions the output echoes, in the
    input parser's grammar (M50). The input's declared units (bohr positions, alat cell) are
    the output echo's declared units, so the two parsers must land the same canonical values."""
    return f"""\
&CONTROL
   calculation = 'relax',
/
&SYSTEM
   ibrav = 0, nat = 3, ntyp = 2,
   celldm(1) = {ALAT_BOHR},
/
&ELECTRONS
   conv_thr = 1e-08,
/
ATOMIC_SPECIES
   O 15.999 o.pbe.UPF
   H  1.008 h.pbe.UPF
ATOMIC_POSITIONS {{bohr}}
   O  {X_BOHR}  {X_BOHR}  {X_BOHR}
   H  {H_BOHR}  {X_BOHR}  {X_BOHR}
   H  {X_BOHR}  {H_BOHR}  {X_BOHR}
CELL_PARAMETERS {{alat}}
   1.0 0.0 0.0
   0.0 1.0 0.0
   0.0 0.0 1.0
"""
